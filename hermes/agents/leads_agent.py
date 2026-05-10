import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

from hermes.tools.env import load_env
from hermes.tools.paths import memory_root
from hermes.tools.storage import write_json, utc_now_iso
from hermes.tools.telegram import post_message
from hermes.tools.replyiq_admin import leads_recent


def _read_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _infer_lang_from_email(email: str, default_lang: str = "en") -> str:
    e = (email or "").lower()
    # Very lightweight heuristic.
    if e.endswith(".de") or e.endswith(".at") or e.endswith(".ch"):
        return "de"
    if e.endswith(".es"):
        return "es"
    return default_lang


def _add_utm(url: str, params: dict[str, str]) -> str:
    if not url:
        return url
    u = urlsplit(url)
    q = dict(parse_qsl(u.query, keep_blank_values=True))
    q.update({k: v for k, v in params.items() if v is not None})
    return urlunsplit((u.scheme, u.netloc, u.path, urlencode(q), u.fragment))


def _build_outreach_payload(*, lead: dict, link: str, lang: str) -> dict:
    email = lead.get("email", "")
    first_name = (email.split("@", 1)[0] or "there").replace(".", " ").strip() or "there"
    source = lead.get("source") or "landing"

    # Keep copy short, value-first, and no legal claims.
    if lang == "es":
        subject = "¿Te lo envío? (checklist + demo)"
        body = (
            f"Hola {first_name},\n\n"
            "HR responde las mismas preguntas cada semana (PTO, políticas, gastos, permisos).\n\n"
            "Preparé una mini-demo para que tus empleados reciban respuestas citando la sección exacta del handbook.\n"
            "Si quieres, te paso el link y me dices qué 5 preguntas harías primero.\n\n"
            f"Link de demo: {link}\n\n"
            "Sin venta."
        )
        telegram_text = (
            f"{first_name}—pregunta rápida. ¿Te paso el link del demo 14 días (sin tarjeta)?\n"
            f"Tu email: {email}"
        )
        whatsapp_text = (
            f"Hola {first_name}! ¿Te mando el link del demo (prueba 14 días, sin tarjeta)?\n"
            f"{link}"
        )
        linkedin_dm = (
            f"Hola {first_name}, quick one. HR pierde tiempo respondiendo lo mismo cada semana.\n"
            "Tengo un demo que responde con citas del handbook (sin inventar).\n"
            f"¿Te lo envío? {link}"
        )
    elif lang == "de":
        subject = "Soll ich es Ihnen schicken? (Demo + Checkliste)"
        body = (
            f"Hallo {first_name},\n\n"
            "HR beantwortet jede Woche dieselben Fragen (Urlaub, Richtlinien, Spesen, Freistellungen).\n\n"
            "Ich habe eine kurze Demo vorbereitet, bei der Antworten auf eurem Handbook basieren und die exakte Stelle zitieren.\n"
            "Wenn Sie möchten, schicke ich Ihnen den Link und Sie sagen mir Ihre Top-5 Fragen.\n\n"
            f"Demo-Link: {link}\n\n"
            "Kein Pitch."
        )
        telegram_text = (
            f"{first_name}—kurze Frage. Darf ich Ihnen den Demo-Link (14 Tage Test ohne Kreditkarte) schicken?\n"
            f"{email}"
        )
        whatsapp_text = (
            f"Hallo {first_name}! Soll ich Ihnen den Demo-Link schicken? (14 Tage Test, ohne Kreditkarte)\n"
            f"{link}"
        )
        linkedin_dm = (
            f"Hallo {first_name}, quick one. HR verliert Zeit durch wiederkehrende Handbook-Fragen.\n"
            "Ich habe eine Demo, die mit Zitaten aus dem Handbook antwortet (ohne zu raten).\n"
            f"Soll ich es Ihnen schicken? {link}"
        )
    else:
        subject = "Want me to send it? (demo + checklist)"
        body = (
            f"Hi {first_name},\n\n"
            "HR teams lose hours every week answering the same handbook questions (PTO, policies, expenses, sick leave).\n\n"
            "I put together a short demo where answers cite the exact handbook section (no guessing).\n"
            "If you want, I’ll send the link and you can tell me your top 5 questions to test first.\n\n"
            f"Demo link: {link}\n\n"
            "No pitch."
        )
        telegram_text = (
            f"{first_name}—quick one. Want me to send the free 14-day demo link (no credit card)?\n"
            f"{email}"
        )
        whatsapp_text = (
            f"Hi {first_name}! Want me to send the free 14-day demo link (no credit card)?\n"
            f"{link}"
        )
        linkedin_dm = (
            f"Hi {first_name}, quick one. HR teams lose time repeating the same handbook questions.\n"
            "I have a short demo where answers cite the exact handbook section (no guessing).\n"
            f"Want me to send it? {link}"
        )

    return {
        "lead": {
            "id": lead.get("id"),
            "email": lead.get("email"),
            "source": source,
            "created_at": lead.get("created_at"),
        },
        "language": lang,
        "platforms": {
            "email": {"subject": subject, "body": body},
            "telegram": {"text": telegram_text},
            "whatsapp": {"text": whatsapp_text},
            "linkedin_dm": {"text": linkedin_dm},
        },
        "notes": {
            "privacy": "DRAFTS include lead email. Share carefully."
        },
        "link": link,
    }


def run_leads_outreach(args: argparse.Namespace) -> None:
    load_env()

    root = memory_root()  # hermes/memory
    out_dir = root / "outreach" / "drafts"
    state_path = root / "outreach" / "leads_outreach_state.json"
    out_dir.mkdir(parents=True, exist_ok=True)

    state = _read_json(state_path)
    processed_ids = set(str(x) for x in state.get("processed_ids", []))

    default_lang = (getattr(args, "default_lang", None) or __import__("os").environ.get("OUTREACH_LOCALE_DEFAULT", "EN")).upper()
    default_lang = {"EN": "en", "ES": "es", "DE": "de"}.get(default_lang, "en")

    link = (args.link or "").strip() or __import__("os").environ.get("OUTREACH_LINK", "").strip()
    if not link:
        # If outreach link isn't set, generate a placeholder.
        link = "https://example.com/product.html"

    # Query recent leads
    limit = int(getattr(args, "limit", 30) or 30)
    since_hours = int(getattr(args, "since_hours", 24) or 24)
    resp = leads_recent(limit=limit, since_hours=since_hours)
    leads = resp.get("leads") or []

    new_count = 0
    draft_files = []

    for lead in leads:
        lead_id = str(lead.get("id"))
        if lead_id in processed_ids:
            continue

        lang = _infer_lang_from_email(lead.get("email", ""), default_lang=default_lang)

        # Track by lead id + platform (for later analytics).
        tracked_link = _add_utm(
            link,
            {
                "utm_source": "lead",
                "utm_medium": "outreach",
                "utm_campaign": f"lead_{lead_id}",
                "utm_content": lang,
            },
        )

        payload = _build_outreach_payload(lead=lead, link=tracked_link, lang=lang)

        out_file = out_dir / f"lead_{lead_id}_draft_{datetime.now(timezone.utc).date().isoformat()}.json"
        write_json(out_file, payload)

        processed_ids.add(lead_id)
        new_count += 1
        draft_files.append(str(out_file))

    # Persist state (append-only semantics over processed ids)
    state["processed_ids"] = sorted(processed_ids, key=lambda x: int(x) if str(x).isdigit() else 0)
    state["updated_at"] = utc_now_iso()
    write_json(state_path, state)

    # Operational notification (internal)
    if not getattr(args, "dry_run", False):
        if new_count:
            msg = (
                f"📬 Leads outreach: drafted {new_count} new lead(s) ({datetime.now(timezone.utc).date().isoformat()}).\n"
                f"Draft files: {', '.join(draft_files[:3])}{'...' if len(draft_files) > 3 else ''}"
            )
            post_message("TELEGRAM_CHAT_GROWTH", msg)
        else:
            post_message(
                "TELEGRAM_CHAT_GROWTH",
                f"📬 Leads outreach: no new leads since last check (since_hours={since_hours}, limit={limit}).",
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--limit", type=int, default=30)
    parser.add_argument("--since-hours", type=int, default=24)
    parser.add_argument("--link", type=str, default="")
    parser.add_argument("--default-lang", type=str, default="en")
    run_leads_outreach(parser.parse_args())

import argparse
from datetime import datetime

from hermes.tools.env import load_env
from hermes.tools.paths import memory_root
from hermes.tools.storage import write_json, utc_now_iso


DM_TEMPLATES = {
    "en": [
        (
            "Hi {{first_name}}—quick one. HR teams lose hours every week answering the same handbook questions (PTO, policies, expenses). I wrote a short checklist: “5 Signs Your HR Team Is Drowning in Repetitive Questions.” Want me to send it?",
            "If you reply with your top 5 employee questions, I’ll tell you which are most automatable first (and which should stay human). No pitch.",
            "Want the free 14-day trial link (no credit card)? I can send it here: {{link}}",
        )
    ],
    "es": [
        (
            "Hola {{first_name}}—pregunta rápida. RR. HH. pierde horas cada semana con las mismas preguntas del manual (vacaciones, políticas, gastos). Escribí este checklist: “5 señales de RR. HH. saturado con preguntas repetitivas”. ¿Te lo envío?",
            "Si me dices tus 5 preguntas más frecuentes, te indico cuáles se pueden automatizar primero (y cuáles conviene que siga viendo RR. HH.). Sin venta.",
            "¿Te mando el link de prueba gratis de 14 días (sin tarjeta)? Aquí: {{link}}",
        )
    ],
    "de": [
        (
            "Hallo {{first_name}}, kurze Frage. HR-Teams verlieren jede Woche Zeit mit immer denselben Handbuch-Fragen (Urlaub, Richtlinien, Spesen). Ich habe eine kurze Checklist: „5 Anzeichen, dass Ihr HR-Team in repetitiven Fragen ertrinkt.“ Soll ich sie Ihnen schicken?",
            "Wenn Sie mir Ihre Top-5 Mitarbeiterfragen schicken, sage ich Ihnen, welche sich zuerst am sinnvollsten automatisieren lassen (und was bei Menschen bleiben sollte). Kein Pitch.",
            "Wenn das passt: 14-Tage-Testlink (ohne Kreditkarte). Ich sende ihn Ihnen hier: {{link}}",
        )
    ],
}


def _render(template: str, first_name: str, link: str) -> str:
    return template.replace("{{first_name}}", first_name).replace("{{link}}", link)


def run_outreach_generation(args: argparse.Namespace) -> None:
    load_env()

    link = (args.link or "").strip() or __import__("os").environ.get("OUTREACH_LINK", "").strip()
    if not link:
        link = "{{link}}"  # placeholder

    first_name = getattr(args, "first_name", None) or "Alex"

    payload = {
        "type": "outreach_drafts",
        "at": utc_now_iso(),
        "languages": ["en", "es", "de"],
        "platform": "linkedin_dm",
        "first_name": first_name,
        "link": link,
        "drafts": {},
    }

    for lang, variants in DM_TEMPLATES.items():
        # Pick the first variant for MVP
        v = variants[0]
        payload["drafts"][lang] = [
            _render(v[0], first_name, link),
            _render(v[1], first_name, link),
            _render(v[2], first_name, link),
        ]

    out = memory_root() / "growth" / f"outreach_linkedin_dm_{datetime.utcnow().date().isoformat()}.json"
    write_json(out, payload)

    if not getattr(args, "dry_run", False):
        print(f"[growth-agent] wrote {out}")

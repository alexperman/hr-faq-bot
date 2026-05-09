import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

from hermes.tools.env import load_env
from hermes.tools.paths import memory_root
from hermes.tools.storage import write_json, utc_now_iso
from hermes.tools.telegram import post_message


LANGS = ["en", "es", "de"]

# Pain points grounded in the existing presell/landing content.
PAIN_POINTS = [
    "PTO and time-off rollover",
    "policy questions (handbook sections)",
    "remote work / work-from-home rules",
    "expense and reimbursement process",
    "sick leave usage rules",
    "parental leave basics",
    "benefits questions (high frequency)",
]

TRUST_POINTS = [
    "Answers cite the handbook section they came from",
    "If the information is unclear, it flags for HR review instead of guessing",
    "Instant answers, 24/7 (including evenings and weekends)",
    "14-day free trial, no credit card",
]


def _localize(lang: str, en_text: str) -> str:
    # MVP localization: provide tailored short lines for the CTA + main hook.
    # Keep everything else in English to reduce translation risk.
    # (We still avoid generic chatbot language.)
    if lang == "es":
        mapping = {
            "Want me to send it?": "¿Te lo envío?",
            "No pitch. Want the link?": "Sin venta. ¿Te mando el link?",
            "14-day trial link (no credit card)": "link de prueba 14 días (sin tarjeta)",
            "I’ll send it here": "Te lo envío aquí",
            "Reply with your top 5 questions": "Respóndeme con tus 5 preguntas más frecuentes",
            "HR answers 47 times a month": "HR responde 47 veces al mes",
        }
        return mapping.get(en_text, en_text)
    if lang == "de":
        mapping = {
            "Want me to send it?": "Soll ich es Ihnen schicken?",
            "No pitch. Want the link?": "Kein Pitch. Soll ich Ihnen den Link schicken?",
            "14-day trial link (no credit card)": "14-Tage-Testlink (ohne Kreditkarte)",
            "I’ll send it here": "Ich sende es Ihnen hier",
            "Reply with your top 5 questions": "Antworten Sie mir mit Ihren Top-5-Fragen",
            "HR answers 47 times a month": "HR beantwortet 47 Mal pro Monat",
        }
        return mapping.get(en_text, en_text)
    return en_text


def _dm_sequence(lang: str, first_name: str, link: str) -> list[str]:
    if lang == "es":
        return [
            f"Hola {first_name}—pregunta rápida. RR. HH. pierde horas cada semana con las mismas preguntas del manual ({PAIN_POINTS[0]}, políticas, gastos). Escribí un checklist: \"5 señales de RR. HH. saturado con preguntas repetitivas\". ¿Te lo envío?",
            f"Si me dices tus 5 preguntas más frecuentes, te indico cuáles se pueden automatizar primero (y cuáles conviene que siga viendo RR. HH.). Sin venta.",
            f"Si te interesa, { _localize('I’ll send it here', 'I’ll send it here') }: {link} (prueba gratis 14 días, sin tarjeta).",
        ]

    if lang == "de":
        return [
            f"Hallo {first_name}, kurze Frage. HR-Teams verlieren jede Woche Zeit mit immer denselben Handbuch-Fragen ({PAIN_POINTS[0]}, Richtlinien, Spesen). Ich habe eine kurze Checklist: \"5 Anzeichen, dass Ihr HR-Team in repetitiven Fragen ertrinkt\". Soll ich sie Ihnen schicken?",
            "Wenn Sie mir Ihre Top-5 Mitarbeiterfragen schicken, sage ich Ihnen, welche sich zuerst am sinnvollsten automatisieren lassen (und was bei Menschen bleiben sollte). Kein Pitch.",
            f"Wenn das passt: {link} (14-Tage-Testlink ohne Kreditkarte).",
        ]

    # English
    return [
        f"Hi {first_name}—quick one. HR teams lose hours every week answering the same handbook questions ({PAIN_POINTS[0]}, policies, expenses). I wrote a short checklist: \"5 Signs Your HR Team Is Drowning in Repetitive Questions\". Want me to send it?",
        "Reply with your top 5 employee questions and I’ll tell you which ones are most automatable first (and which should stay human). No pitch.",
        f"Want the free 14-day trial link (no credit card)? I’ll send it here: {link}",
    ]


def _twitter_thread(lang: str) -> list[str]:
    # Keep threads short and educational, not salesy.
    if lang == "es":
        return [
            "La mayoría de preguntas de RR. HH. son repetitivas (PTO, políticas, gastos, permisos).",
            "Problema: tus empleados preguntan. HR responde. Y el tiempo se va…",
            "Solución práctica: un asistente con tus documentos (manual + políticas) que responda con contexto.",
            "Lo importante: que cite la sección exacta del handbook.",
            "Cuando no está claro, que se marque para revisión de RR. HH. (sin adivinar).",
            "Meta: liberar horas para onboarding, cultura y trabajo estratégico.",
        ]
    if lang == "de":
        return [
            "Die meisten HR-Fragen sind wiederkehrend (Urlaub, Richtlinien, Spesen, Freistellungen).",
            "Folge: HR beantwortet immer wieder dieselben Punkte. Das kostet Zeit.",
            "Pragmatische Lösung: ein Assistent, der aus euren HR-Dokumenten antwortet.",
            "Wichtig: Antworten mit Verweis auf die exakte Handbuch-Stelle.",
            "Wenn etwas fehlt: für HR zur Prüfung markieren (kein Raten).",
            "Ziel: Stunden freimachen für Onboarding & strategische Arbeit.",
        ]

    return [
        "Most HR questions are repetitive: PTO, policies, expenses, sick leave.",
        "Employees ask. HR answers. The same 12 questions repeat every week.",
        "Fix: give the handbook a voice, powered by your actual documents.",
        "Requirement: answers cite the exact handbook section.",
        "When unsure, flag for HR review instead of guessing.",
        "Outcome: fewer inbox hours, more time for real HR work.",
    ]


def _telegram_post(lang: str, link: str) -> str:
    if lang == "es":
        return (
            "RR. HH. responde las mismas preguntas cada semana (PTO, políticas, gastos, bajas)… y eso roba tiempo.\n\n"
            "Hice un checklist corto: \"5 señales de RR. HH. saturado con preguntas repetitivas\".\n"
            "Si quieres, te paso la prueba gratis de 14 días (sin tarjeta): " + link
        )
    if lang == "de":
        return (
            "HR beantwortet jede Woche dieselben Fragen (Urlaub, Richtlinien, Spesen, Krankmeldungen) … das kostet Zeit.\n\n"
            "Ich habe eine kurze Checklist: \"5 Anzeichen, dass Ihr HR-Team in repetitiven Fragen ertrinkt\".\n"
            "Wenn Sie möchten, sende ich Ihnen den 14-Tage-Testlink (ohne Kreditkarte): " + link
        )

    return (
        "HR teams lose hours every week to the same handbook questions (PTO, policies, expenses, sick leave).\n\n"
        "I wrote a short checklist: \"5 Signs Your HR Team Is Drowning in Repetitive Questions\".\n"
        "If you want it, I’ll send you the free 14-day trial link (no credit card): "
        + link
    )


def _landing_variants(lang: str) -> list[dict]:
    # Variants for A/B testing (headlines + 2 bullets).
    if lang == "es":
        return [
            {
                "headline": "Tu manual de empleados, con respuestas instantáneas",
                "bullets": ["Respuestas con la sección exacta del handbook", "Si falta info, se marca para revisión de RR. HH."],
            },
            {
                "headline": "Menos inbox, más onboarding (24/7)",
                "bullets": ["Respuestas en segundos", "Prueba gratis 14 días, sin tarjeta"],
            },
        ]
    if lang == "de":
        return [
            {
                "headline": "Ihr Employee Handbook, lebendig 24/7",
                "bullets": ["Antworten mit Verweis auf die exakte Handbuch-Stelle", "Unklare Fälle für HR zur Prüfung markieren"],
            },
            {
                "headline": "Weniger E-Mail-Last, mehr strategische HR-Zeit",
                "bullets": ["Sofortige Antworten", "14-Tage-Testlink ohne Kreditkarte"],
            },
        ]

    return [
        {
            "headline": "Your employee handbook, alive 24/7",
            "bullets": ["Answers cite the exact handbook section", "Unclear info gets flagged for HR review"],
        },
        {
            "headline": "Less inbox. More onboarding.",
            "bullets": ["Instant answers in seconds", "14-day free trial, no credit card"],
        },
    ]


def _community_targets(lang: str) -> dict:
    # Provide search queries and community types (no claims about specific org policies).
    return {
        "types": [
            "HR manager communities",
            "Small business HR discussions",
            "Workplace policy & benefits Q&A",
            "HR automation / operations threads",
        ],
        "search_queries": [
            "site:reddit.com human resources recurring questions",
            "site:reddit.com HR PTO policy remote work reimbursement",
            "HR handbook FAQ bot",
            "employee questions handbook assistant",
            "RRHH preguntas repetitivas",
            "HR wiederkehrende Fragen Handbuch",
        ],
        "notes": "Test posts with value-first educational excerpts (no links in the first comment).",
    }


def run_outreach_generation(args: argparse.Namespace) -> None:
    load_env()

    link = (args.link or "").strip() or __import__("os").environ.get("OUTREACH_LINK", "").strip()
    if not link:
        link = "{{link}}"  # placeholder

    first_name = getattr(args, "first_name", None) or "Alex"
    at = utc_now_iso()

    drafts = {}
    for lang in LANGS:
        drafts[lang] = {
            "platform": "linkedin_dm",
            "linkedin_dm_sequence": _dm_sequence(lang, first_name, link),
            "twitter_thread": _twitter_thread(lang),
            "telegram_post": _telegram_post(lang, link),
            "landing_page_variants": _landing_variants(lang),
        }

    pain_point_analysis = {
        "top_pains": PAIN_POINTS,
        "trust_points": TRUST_POINTS,
        "why_now": "HR teams answer the same handbook questions repeatedly; an instant, grounded assistant reduces inbox load.",
    }

    presell_funnel = {
        "pre_sell_hook": "Lead with a short checklist article that names the recurring question set.",
        "cta_copy": {
            "en": "Want the checklist + the 14-day trial link?",
            "es": "¿Quieres el checklist y el link de prueba de 14 días?",
            "de": "Möchten Sie den Checklist + den 14-Tage-Testlink?",
        },
        "friction_reducers": [
            "No credit card",
            "10-minute setup",
            "Answers cite handbook sections",
            "Unclear cases flagged for HR review",
        ],
    }

    communities = {lang: _community_targets(lang) for lang in LANGS}

    payload = {
        "type": "growth_agent_daily_drafts",
        "at": at,
        "markets": ["US", "UK", "Europe", "LATAM"],
        "languages": LANGS,
        "link": link,
        "drafts": drafts,
        "pain_point_analysis": pain_point_analysis,
        "presell_funnel": presell_funnel,
        "community_targets": communities,
    }

    root = memory_root()
    out = root / "growth_experiments" / f"growth_drafts_{datetime.now().date().isoformat()}.json"
    write_json(out, payload)

    summary = {
        "type": "growth_agent_daily_summary",
        "at": at,
        "draft_files": [str(out)],
        "outputs": {
            "languages_generated": LANGS,
            "linkedin_dm_sequences_per_lang": 1,
            "twitter_threads_per_lang": 1,
            "telegram_posts_per_lang": 1,
            "landing_page_variants_per_lang": len(_landing_variants("en")),
        },
        "recommended_next": [
            "Pick 1 language lane for the next outreach batch (start with English, then ES, then DE).",
            "Run DM outreach value-first, with max 1 follow-up. Send the link only to engaged replies.",
            "After 7-10 days, compare opt-in rates by language and adjust hooks.",
        ],
    }

    sums = root / "daily_summaries" / f"growth_agent_daily_{datetime.now().date().isoformat()}.json"
    write_json(sums, summary)

    post_message(
        "TELEGRAM_CHAT_GROWTH",
        f"📣 Daily growth drafts ready ({datetime.now(timezone.utc).date().isoformat()}), languages=EN/ES/DE",
    )

    if not getattr(args, "dry_run", False):
        print(f"[growth-agent] wrote {out} and {sums}")

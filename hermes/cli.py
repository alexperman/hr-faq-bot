import argparse
from hermes.agents.infra_agent import run_infra_check
from hermes.agents.memory_agent import run_memory_maintenance
from hermes.agents.growth_agent import run_outreach_generation
from hermes.agents.analytics_agent import run_analytics
from hermes.agents.kb_agent import run_kb_assist
from hermes.agents.support_agent import run_support


def main():
    parser = argparse.ArgumentParser(prog="hermes")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub_infra = sub.add_parser("infra-agent")
    sub_infra.set_defaults(func=lambda args: run_infra_check(args))

    sub_mem = sub.add_parser("memory-agent")
    sub_mem.set_defaults(func=lambda args: run_memory_maintenance(args))

    sub_growth = sub.add_parser("growth-agent")
    sub_growth.set_defaults(func=lambda args: run_outreach_generation(args))

    sub_analytics = sub.add_parser("analytics-agent")
    sub_analytics.set_defaults(func=lambda args: run_analytics(args))

    sub_kb = sub.add_parser("kb-agent")
    sub_kb.set_defaults(func=lambda args: run_kb_assist(args))

    sub_sup = sub.add_parser("support-agent")
    sub_sup.set_defaults(func=lambda args: run_support(args))

    # Optional: select date/source
    parser.add_argument("--dry-run", action="store_true")

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()

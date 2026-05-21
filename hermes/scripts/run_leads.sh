#!/bin/bash
# Leads: outreach drafting every 10min
cd /root/hr-faq-bot
source backend/.venv/bin/activate
export PYTHONPATH="/root/hr-faq-bot:$PYTHONPATH"
python3 -c "
import sys; sys.path.insert(0, '/root/hr-faq-bot')
from hermes.tools.env import load_env
load_env('/root/hr-faq-bot/hermes/.env')
from hermes.agents.leads_agent import run_leads_outreach
import argparse
run_leads_outreach(argparse.Namespace(link='', default_lang='en', limit=30, since_hours=24, dry_run=False))
"

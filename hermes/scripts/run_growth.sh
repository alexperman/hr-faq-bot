#!/bin/bash
# Growth: multilingual outreach daily
cd /root/hr-faq-bot
source backend/.venv/bin/activate
export PYTHONPATH="/root/hr-faq-bot:$PYTHONPATH"
python3 -c "
import sys; sys.path.insert(0, '/root/hr-faq-bot')
from hermes.tools.env import load_env
load_env('/root/hr-faq-bot/hermes/.env')
from hermes.agents.growth_agent import run_outreach_generation
import argparse
run_outreach_generation(argparse.Namespace(link='', first_name='Alex', default_lang='en', limit=30, since_hours=24, dry_run=False))
"

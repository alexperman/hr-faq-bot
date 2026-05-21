#!/bin/bash
# Infra: health check
cd /root/hr-faq-bot
source backend/.venv/bin/activate
export PYTHONPATH="/root/hr-faq-bot:$PYTHONPATH"
python3 -c "
import sys; sys.path.insert(0, '/root/hr-faq-bot')
from hermes.tools.env import load_env
load_env('/root/hr-faq-bot/hermes/.env')
from hermes.agents.infra_agent import run_infra_health_check
import argparse
run_infra_health_check(argparse.Namespace())
"

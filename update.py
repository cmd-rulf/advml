from base64 import b64decode
from dotenv import load_dotenv, dotenv_values
from logging import FileHandler, StreamHandler, basicConfig, error as log_error, info as log_info, INFO
from os import path as ospath, environ, remove
from pymongo import MongoClient
from re import sub as resub
from requests import get as rget
from subprocess import run as srun
from sys import exit


if ospath.exists('log.txt'):
    with open('log.txt', 'r+') as f:
        f.truncate(0)

if ospath.exists('rlog.txt'):
    remove('rlog.txt')

basicConfig(format='%(asctime)s: [%(levelname)s: %(filename)s - %(lineno)d] ~ %(message)s',
            handlers=[FileHandler('log.txt'), StreamHandler()],
            datefmt='%d-%b-%y %I:%M:%S %p',
            level=INFO)

load_dotenv('config.env', override=True)

if BOT_TOKEN := environ.get('BOT_TOKEN', ''):
    bot_id = BOT_TOKEN.split(':', 1)[0]
else:
    log_error('BOT_TOKEN variable is missing! Exiting now')
    exit(1)

if DATABASE_URL := environ.get('DATABASE_URL', ''):
    if not DATABASE_URL.startswith('mongodb'):
        try:
            DATABASE_URL = b64decode(resub('ini|adalah|pesan|yang|sangat|rahasia', '', DATABASE_URL)).decode('utf-8')
        except:
            pass
    try:
        conn = MongoClient(DATABASE_URL)
        db = conn.mltb
        old_config = db.settings.deployConfig.find_one({'_id': bot_id})
        config_dict = db.settings.config.find_one({'_id': bot_id})
        if old_config:
            del old_config['_id']
        if (old_config and old_config == dict(dotenv_values('config.env')) or not old_config) and config_dict:
            environ['UPSTREAM_REPO'] = config_dict.get('UPSTREAM_REPO')
            environ['UPSTREAM_BRANCH'] = config_dict.get('UPSTREAM_BRANCH')
            environ['UPDATE_EVERYTHING'] = str(config_dict.get('UPDATE_EVERYTHING'))
        conn.close()
    except Exception as e:
        log_error('Database ERROR: %s', e)

if environ.get('UPDATE_EVERYTHING', 'False').lower() == 'true':
    srun("pip3 list --outdated --format=freeze | grep -v '^\-e' | cut -d = -f 1 | xargs -n1 pip3 install -U", shell=True)

if (UPSTREAM_REPO := environ.get('UPSTREAM_REPO')) and (UPSTREAM_BRANCH := environ.get('UPSTREAM_BRANCH')):
    if 'gist.githubusercontent.com' in UPSTREAM_REPO:
        UPSTREAM_REPO = rget(UPSTREAM_REPO).text.strip()
    if ospath.exists('.git'):
        srun(['rm', '-rf', '.git'], check=True)
    update = srun([f'git init -q \
                     && git config --global user.email e.luckm4n@gmail.com \
                     && git config --global user.name Honeyrs \
                     && git add . \
                     && git commit -sm update -q \
                     && git remote add origin {UPSTREAM_REPO} \
                     && git fetch origin -q \
                     && git reset --hard origin/{UPSTREAM_BRANCH} -q'], shell=True, check=True)
    if update.returncode == 0:
        log_info(f'Successfully updated with latest commit from UPSTREAM_REPO ~ {UPSTREAM_BRANCH.upper()} Branch.')
    else:
        log_error('Something went wrong while updating, check UPSTREAM_REPO if valid or not!')

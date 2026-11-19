"""Local maintenance only; never prints passwords, hashes or session tokens."""
import argparse
import getpass
import json
import os
from pathlib import Path
import re
from .store import AuthStore
from ..core.config import Settings


def legacy_credentials(path, legacy_username=None):
    text=Path(path).read_text()
    def value(labels):
        m=re.search(r'(?im)^\s*(?:'+labels+r')\s*[:：=]\s*(.+?)\s*$',text)
        if not m:raise ValueError('凭据文件格式无法识别；请使用交互初始化，不会输出文件内容')
        return m.group(1).strip().strip('`').strip('"').strip("'")
    if legacy_username and len(text.strip().splitlines())==1 and 0<len(text.strip())<=256:
        return legacy_username,text.strip()
    return value(r'username|user|用户名|账号|账户'),value(r'password|pass|密码')


def main():
    parser=argparse.ArgumentParser()
    sub=parser.add_subparsers(dest='command',required=True)
    init=sub.add_parser('init-admin')
    init.add_argument('--legacy-file',type=Path)
    init.add_argument('--legacy-username')
    init.add_argument('--verify-origin')
    recovery=sub.add_parser('reset-admin-password')
    recovery.add_argument('--confirm',action='store_true')
    revoke=sub.add_parser('revoke-session')
    revoke.add_argument('--input',type=Path,required=True)
    issue=sub.add_parser('issue-session')
    issue.add_argument('--output',type=Path,required=True)
    issue.add_argument('--minutes',type=int,default=5,choices=range(1,16))
    args=parser.parse_args()
    s=AuthStore.from_env(Settings.from_env().data_dir)
    try:
        if args.command=='init-admin':
            if s.primary_id():
                print('管理员已存在，未覆盖密码或现有资料。');return
            if args.legacy_file:name,password=legacy_credentials(args.legacy_file,args.legacy_username)
            else:name=input('管理员账号：');password=getpass.getpass('沿用的管理员密码：')
            if args.verify_origin:
                import httpx
                origin=args.verify_origin.rstrip('/')
                if origin!='https://paper.matchesai.vip':raise ValueError('只允许验证当前已部署站点')
                with httpx.Client(timeout=15,follow_redirects=False) as client:
                    if client.get(origin+'/health').status_code!=401:raise ValueError('现有入口未返回认证挑战，未初始化')
                    if client.get(origin+'/health',auth=(name,password)).status_code!=200:raise ValueError('现有站点认证未通过，未初始化')
            s.bootstrap(name,password)
            print('管理员已初始化，原资料归属管理员；公开注册关闭，普通账号登录关闭。')
        elif args.command=='reset-admin-password':
            from .store import new_password,password_hash
            if not args.confirm:raise ValueError('恢复操作需要 --confirm')
            ident=s.primary_id()
            if not ident:raise ValueError('管理员尚未初始化')
            password=getpass.getpass('新的管理员应用密码：')
            repeated=getpass.getpass('再次输入：')
            if password!=repeated:raise ValueError('两次密码不一致')
            encoded=password_hash(new_password(password))
            s.db.execute('UPDATE accounts SET password_hash=?,session_version=session_version+1 WHERE id=?',(encoded,ident))
            s.audit(ident,'local-admin-password-recovery',ident);s.db.commit()
            print('管理员应用密码已更新，所有旧会话失效。站点入口认证未改变。')
        elif args.command=='revoke-session':
            saved=json.loads(args.input.read_text())
            s.revoke(saved['token'])
            args.input.unlink()
            print('维护会话已撤销，私有文件已删除。')
        else:
            ident=s.primary_id();account=s.account(ident)
            if not s.login_allowed(account):raise ValueError('管理员尚未初始化或不可用')
            if args.output.exists():raise ValueError('输出文件已存在，未覆盖')
            token,csrf=s.issue_session(account,minutes=args.minutes)
            s.audit(ident,'maintenance-session',ident);s.db.commit()
            fd=os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
            with os.fdopen(fd,'w') as f:json.dump({'token':token,'csrf':csrf,'cookie_name':s.cookie_name},f)
            print('短期维护会话已写入私有文件；检查后删除文件，最长 15 分钟过期。')
    finally:s.close()

if __name__=='__main__':main()

import sys
import time
import paramiko

if hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')

HOST = "8.219.243.65"
PORT = 22
USER = "root"
PASS = "posid00!!"

LOCAL_ZIP = r"c:\Pjt\kpicCafeteria\dist\cafeteria-update.zip"
REMOTE_ZIP = "/tmp/cafeteria-update.zip"

LOCAL_SH = r"c:\Pjt\kpicCafeteria\scratch\deploy_remote.sh"
REMOTE_SH = "/tmp/deploy_remote.sh"

def deploy():
    print(f"[*] Connecting to {HOST}:{PORT} as {USER}...")
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(HOST, port=PORT, username=USER, password=PASS, timeout=30)
    print("[+] SSH connection established.")

    sftp = ssh.open_sftp()
    print(f"[*] Uploading {LOCAL_ZIP} -> {REMOTE_ZIP}...")
    def cb(transferred, total):
        pct = (transferred / total) * 100
        sys.stdout.write(f"\r  Progress: {pct:.1f}% ({transferred // 1024} KB / {total // 1024} KB)")
        sys.stdout.flush()
    sftp.put(LOCAL_ZIP, REMOTE_ZIP, callback=cb)
    print("\n[+] cafeteria-update.zip upload complete.")

    print(f"[*] Uploading {LOCAL_SH} -> {REMOTE_SH}...")
    sftp.put(LOCAL_SH, REMOTE_SH)
    sftp.chmod(REMOTE_SH, 0o755)
    sftp.close()
    print("[+] deploy_remote.sh uploaded.")

    print("[*] Executing deploy script on remote server...")
    stdin, stdout, stderr = ssh.exec_command("bash /tmp/deploy_remote.sh", get_pty=True)
    for line in iter(stdout.readline, ""):
        print(line, end="")
    
    exit_status = stdout.channel.recv_exit_status()
    print(f"\n[*] Remote deploy finished with exit status: {exit_status}")

    ssh.close()
    if exit_status != 0:
        print("[-] Deployment failed!")
        sys.exit(1)
    else:
        print("[+] Deployment succeeded!")

if __name__ == '__main__':
    deploy()

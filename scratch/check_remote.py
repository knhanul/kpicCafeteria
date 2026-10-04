import paramiko

ssh = paramiko.SSHClient()
ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
ssh.connect('8.219.243.65', port=22, username='root', password='posid00!!')

_, out, _ = ssh.exec_command('curl -s -L http://127.0.0.1:8080/ | head -n 10')
print('Local 8080 GET:')
print(out.read().decode())

_, out2, _ = ssh.exec_command('grep -rn "8080" /etc/nginx/ 2>/dev/null')
print('Host proxy to 8080:')
print(out2.read().decode())

_, out3, _ = ssh.exec_command('cat /opt/cafeteria/.env | grep -E "PUBLIC_BASE_URL|APP_NAME"')
print('.env configs:')
print(out3.read().decode())

ssh.close()

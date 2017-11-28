wget -qO - http://pkg.bluehorizon.network/bluehorizon.network-public.key | apt-key add -

cat <<EOF > /etc/apt/sources.list.d/bluehorizon.list
deb [arch=amd64] http://pkg.bluehorizon.network/linux/ubuntu xenial-testing main
deb-src [arch=amd64] http://pkg.bluehorizon.network/linux/ubuntu xenial-testing main
EOF

apt-get update

apt-get install -y horizon bluehorizon bluehorizon-ui

cat <<'EOF' > /etc/rsyslog.d/10-horizon-docker.conf
$template DynamicWorkloadFile,"/var/log/workload/%syslogtag:R,ERE,1,DFLT:.*workload-([^\[]+)--end%.log"

:syslogtag, startswith, "workload-" -?DynamicWorkloadFile
& stop
:syslogtag, startswith, "docker/" -/var/log/docker_containers.log
& stop
:syslogtag, startswith, "docker" -/var/log/docker.log
& stop
EOF
service rsyslog restart



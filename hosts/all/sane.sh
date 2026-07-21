apt-get --purge remove systemd-resolved

# systemctl disable systemd-resolved.service
# systemctl stop systemd-resolved.service
# rm /etc/resolv.conf
# echo nameserver 1.1.1.1 > /etc/resolv.conf

git config --global --add safe.directory /root/ietf-123-pcpu

git config --global --add safe.directory /root/ietf-123-pcpu/.git

echo  "export EDITOR=vim" >>  /root/.bashrc
echo  "source /usr/share/bash-completion/completions/git >> /root/.bashrc

git config receive.denyCurrentBranch updateInstead

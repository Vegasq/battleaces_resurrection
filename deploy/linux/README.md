# Live Battle Aces Wine service

These files describe the tested Ubuntu 24.04 / Wine 9 service on the existing
DigitalOcean host. They assume the installed server is `/srv/ba`, the persistent
Wine prefix has already passed its `wine cmd /c echo WINE_OK` check at
`/srv/ba-runtime/wineprefix`, and `ba-dashboard-allowlist.service` is enabled.

Install as root after stopping any manually launched server:

```sh
install -m 755 deploy/linux/ba-server-supervise /usr/local/sbin/ba-server-supervise
install -m 644 deploy/linux/battle-aces-server.service /etc/systemd/system/battle-aces-server.service
systemctl daemon-reload
systemd-analyze verify /etc/systemd/system/battle-aces-server.service
systemctl enable --now battle-aces-server.service
```

Use `systemctl restart battle-aces-server.service` for a graceful restart.
The supervisor sends Ctrl+C through a dedicated tmux console, waits for the
host to exit, and releases Wine helper processes in this service's prefix.
`systemctl status battle-aces-server.service` and the game TCP port provide
the first health checks. The live deployment and boot test are recorded in
`docs/live-droplet-scale-20261108.txt`.

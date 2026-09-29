# Deploying

The site is plain static files, so any web server that can serve a folder will do. On a Proxmox
host the simplest setup is a small LXC container (Debian or Ubuntu, 256 MB RAM is plenty) running
either Caddy or nginx. If you already host another site, you can also add this one as a second
site in the same web server instead of creating a new container.

**Server setup.** In the container, install Caddy (`apt install caddy`) or nginx, create the web
root (for example `mkdir -p /var/www/site`), and give a non-root deploy user write access to it
and an SSH key from your machine. Copy `Caddyfile.example` to `/etc/caddy/Caddyfile` or
`nginx.conf.example` to `/etc/nginx/conf.d/site.conf`, adjust `root`, and reload the server. Both
examples set security headers, gzip, and sensible caching (HTML always revalidates; CSS, images
and PDFs are cached for a week). The content security policy allows no scripts or external
requests, matching the site design.

**Deploying.** From the repository root, run
`DEPLOY_HOST=<container-ip> DEPLOY_USER=deploy DEPLOY_PATH=/var/www/site deploy/deploy.sh`
(add `--dry-run` first to preview). It runs `python3 build.py`, then rsyncs `dist/` with
`--delete`. `DEPLOY_PORT` is optional. Because `--delete` removes anything else in the target
folder, give this site its own directory.

**Domain and HTTPS.** Until a domain exists, browse to the container's IP on your LAN. Once you
have one, point an A/AAAA record at your public IP, forward ports 80 and 443 from the router (or
the existing reverse proxy) to the container, replace `:80` in the Caddyfile with the domain name
(Caddy then handles HTTPS certificates itself), or run `certbot --nginx` for nginx, and enable the
commented `Strict-Transport-Security` header. Finally set `base_url` in `content/site.toml` so
canonical links are generated.

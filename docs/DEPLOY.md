# Deploy ShopBot publicly (free)

Two options, both using the same hardened production setup (`docker-compose.prod.yml`):

| | Option A: Cloudflare quick tunnel | Option B: server with a domain |
|---|---|---|
| Command | `./deploy.sh tunnel` | `./deploy.sh` |
| Needs | Any machine running Docker (e.g. your laptop) | A VM (Oracle Always Free, Hetzner, …) + a domain |
| URL | `https://<random>.trycloudflare.com`, **changes on every restart** | Your own fixed domain |
| Online | While that machine and Docker are running | 24/7 |
| Open ports | None (outbound tunnel) | 80, 443 |

## Option A: Cloudflare quick tunnel (5 minutes, no account)

1. Have the stack's `.env` ready (the same one you use locally).
2. Run (Git Bash on Windows, or any shell on macOS/Linux):
   ```bash
   ./deploy.sh tunnel
   ```
3. It prints `Live at https://….trycloudflare.com`. Share that link.

To stop sharing: `docker compose -f docker-compose.yml -f docker-compose.prod.yml --profile tunnel down`.
Back to local development: `docker compose up -d --remove-orphans`.

Behind the tunnel the gateway rate-limits by Cloudflare's `CF-Connecting-IP` header, so each
visitor gets their own limit (10 messages/minute, 100/day by default: `PUBLIC_RATE_LIMIT_PER_*`).

## Option B: your own server (24/7)

Target: one **Oracle Cloud Always Free** VM (ARM, 4 CPUs, 24 GB RAM) running the same Docker
Compose stack, with **Caddy** providing HTTPS and a free **DuckDNS** domain.
Cost: $0. Time: about 45 minutes, most of it waiting for the first build.

```
Internet ──443──► Caddy (HTTPS) ──► frontend (nginx) ──► gateway ──► chat / catalog / order
                                                         everything else stays internal
```

What the production override (`docker-compose.prod.yml`) changes:

| Setting | Effect |
|---|---|
| Only Caddy publishes ports (80, 443) | Postgres, Redis, Ollama, the services and Prometheus are unreachable from the internet |
| `APP_ENV=prod` | Debug data, GraphiQL and `/eval/*` endpoints are off |
| `DEMO_MODE=true` | Visitors can still pick a demo customer to sign in |
| Grafana on `127.0.0.1:3000`, password required | Open it through an SSH tunnel (step 9) |
| `restart: unless-stopped` | Services come back after a crash or reboot |

## 1. Create the VM

1. Sign up at <https://cloud.oracle.com> (Always Free). A card is needed for identity
   verification only. **Pick your home region carefully**: it can't be changed later.
2. **Compute → Instances → Create instance**
   - Image: **Canonical Ubuntu 24.04** (aarch64)
   - Shape: **Ampere → VM.Standard.A1.Flex**, **4 OCPUs, 24 GB memory** (marked *Always Free-eligible*)
   - Networking: keep "Assign a public IPv4 address" on
   - SSH keys: *Generate a key pair* and **download the private key**
3. "Out of capacity" error? Try another availability domain, or retry later; ARM capacity
   frees up regularly.
4. Note the instance's **public IP address**.

> Oracle can reclaim Always Free instances that stay almost idle for 7 days. Upgrading the
> account to *Pay As You Go* prevents that and still costs nothing within the free limits.

## 2. Open ports 80 and 443

Two firewalls must allow HTTP/HTTPS:

1. **Oracle network**: Networking → Virtual cloud networks → your VCN → Subnet → Default
   security list → *Add ingress rules*: source `0.0.0.0/0`, TCP, destination ports `80` and `443`.
2. **Ubuntu's own firewall** (Oracle images block everything but SSH). After SSHing in:

```bash
ssh -i ~/Downloads/ssh-key.key ubuntu@YOUR_VM_IP
```
```bash
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 80 -j ACCEPT
sudo iptables -I INPUT 6 -m state --state NEW -p tcp --dport 443 -j ACCEPT
sudo netfilter-persistent save
```

## 3. Install Docker

```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
exit
```
Log in again (so the group change applies) and check: `docker compose version`.

## 4. Get a free domain

1. Sign in at <https://www.duckdns.org>, create a subdomain (e.g. `shopbot-yourname`).
2. Set its **current ip** to the VM's public IP.
3. Your site will be `https://shopbot-yourname.duckdns.org`.

## 5. Get the code

```bash
git clone https://github.com/Brownwell1999/Ecomchatbot.git
cd Ecomchatbot
cp .env.example .env
```

## 6. Configure `.env`

Edit with `nano .env` and set at least these values:

| Key | Value |
|---|---|
| `LLM_PROVIDER` | `groq` |
| `LLM_FALLBACKS` | `ollama` |
| `GROQ_API_KEY` | a **new** key from <https://console.groq.com> |
| `JWT_SECRET` | output of `openssl rand -hex 32` |
| `POSTGRES_PASSWORD` | a strong password (set it **before** the first deploy) |
| `RATE_LIMIT_PER_MINUTE` | `10` |
| `RATE_LIMIT_PER_DAY` | `100` (protects your Groq free quota) |
| `DOMAIN` | `shopbot-yourname.duckdns.org` (uncomment the line) |
| `GRAFANA_ADMIN_PASSWORD` | a strong password (uncomment the line) |
| `DEMO_MODE` | `true` (uncomment the line) |

Keep `BUSINESS_DATE` so the demo orders stay returnable. Never commit `.env`.

## 7. Deploy

```bash
./deploy.sh
```
(`./deploy.sh` defaults to the `https` profile: Caddy with automatic certificates.)

The first run takes 15–25 minutes: it builds the images, downloads the Ollama models
(~2.3 GB), seeds the demo data and builds the vector store. Caddy gets the HTTPS certificate
automatically. When it prints `Live at https://…`, open that address.

## 8. Reset the demo data nightly (recommended)

Visitors create returns and feedback; reset them every night at 03:00:

```bash
crontab -e
```
```
0 3 * * * cd $HOME/Ecomchatbot && docker compose -f docker-compose.yml -f docker-compose.prod.yml run --rm seed >> $HOME/shopbot-reset.log 2>&1
```

## 9. Monitoring (Grafana)

From your laptop, tunnel the private port and open <http://localhost:3000>
(user `admin`, password from `.env`):

```bash
ssh -i ~/Downloads/ssh-key.key -L 3000:localhost:3000 ubuntu@YOUR_VM_IP
```

## 10. Updating

Push changes to GitHub from your laptop, then on the server:

```bash
cd ~/Ecomchatbot && ./deploy.sh
```

## Troubleshooting

| Symptom | Check |
|---|---|
| Browser can't connect | Both firewalls (step 2); `docker compose -f docker-compose.yml -f docker-compose.prod.yml ps` |
| Certificate error | DuckDNS IP matches the VM; ports 80 and 443 open. Logs: `… logs caddy` |
| "ShopBot is temporarily unavailable" | Groq key or quota; Ollama fallback is slow on CPU. Logs: `… logs chat-service` |
| "Too many messages" | Rate limits in `.env`, then `./deploy.sh` |
| Anything else | `docker compose -f docker-compose.yml -f docker-compose.prod.yml logs -f --tail 100` |

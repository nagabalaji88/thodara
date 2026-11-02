# Demo hosting (fictional data only)

How to put Thodara on the internet for a demo at no cost. Decision and rules: [ADR-0016](decisions/ADR-0016-demo-hosting.md). **Never enter real customer, supplier or personal data in a demo.**

## Option A: your computer + a free Cloudflare link (works now)

You need: a Windows computer with Docker Desktop (run `start-thodara.bat` once if it is not installed), and an internet connection.

1. Double-click **`start-demo.bat`**. The first run builds the app and takes several minutes.
2. It shows the demo address, for example `https://calm-river-1234.trycloudflare.com`, copies it, and opens it. It also opens **`demo-accounts.txt`** with the sign-in accounts:

   | Account | Role | Give to |
   |---|---|---|
   | priya@srimant.example.com | Owner | Presenter only |
   | arun@srimant.example.com | Administrator | Presenter only |
   | meena@… | Production manager | Prospects |
   | ravi@… | Stores | Prospects |
   | kavya@… | Quality | Prospects |
   | anita@… | Approver | Prospects |
   | vijay@… | Read only | Prospects |

3. Share the address and a non-administrator account with the people watching. Keep the computer awake.
4. Afterwards, double-click **`stop-demo.bat`**. The address stops working. Starting again gives a new address.
5. To start fresh, with the story as it was and new passwords, run **`reset-demo.bat`** while the demo is running.

On Linux or macOS, use `scripts/demo.sh start | url | reset | backup | stop`.

**What the demo shows.** Srimant Auto Parts (DEMO), Bangalore:

- Four pump and motor orders.
- 200 housing castings at Hosur Coaters for powder coating. The supplier reported 120 done, 20 rejected and 60 pending. Stores received 100 and quality accepted 95, holding 5.
- 40 motor shafts at a heat treater with no update, so their status shows as unknown.
- A planned zinc-plating batch.

The delivery-risk board then has a ready order, two short orders and an unknown one to explain.

**Good to know.**

- The demo has its own database. It never touches data in your trial install (`start-thodara.bat`), and both can run at once: the trial on `http://localhost:8080`, the demo on `http://localhost:8090`.
- Cloudflare's free quick tunnels have no uptime promise. They are for demos only.
- The two-step sign-in rule applies to the owner and administrator accounts: they must set it up within 7 days of a reset. Use `reset-demo.bat` before a demo if more than a week has passed.

## Option B: always-on Oracle Cloud free server

A fixed HTTPS address, for example `https://srimant-demo.duckdns.org`, that prospects can open whenever they like. It needs about an hour the first time.

### What you do once (needs your accounts)

1. **DuckDNS name (free).** Sign in at [duckdns.org](https://www.duckdns.org) with Google or GitHub. Add a name, for example `srimant-demo`, and copy your **token** from the top of the page.
2. **Oracle Cloud account.** Sign up at [oracle.com/cloud/free](https://www.oracle.com/cloud/free/). Choose **India South (Hyderabad)** or **India West (Mumbai)** as the home region; it cannot be changed later. A card is needed for verification. Stay within "Always Free" resources and it is not charged.
3. **Create the VM.** Compute > Instances > Create:
   - Image: **Canonical Ubuntu 24.04**.
   - Shape: **Ampere (VM.Standard.A1.Flex)**, 2 OCPU and 12 GB memory, within the Always Free allowance.
   - Add your SSH key, then create it.

   If Oracle says it is "out of capacity", try another availability domain or try again later.
4. **Open the web ports in Oracle's network.** On the instance page, open the subnet, then its Security List. Add **ingress rules** for TCP **80** and **443** from `0.0.0.0/0`.

### What the script does (on the VM)

Connect with `ssh ubuntu@<public-ip>` and run:

```bash
git clone https://github.com/nagabalaji88/thodara.git
cd thodara
scripts/oracle-setup.sh srimant-demo <your-duckdns-token> <your-email>
```

`scripts/oracle-setup.sh`:

- installs Docker;
- opens ports 80 and 443 in the VM's own firewall (Oracle's Ubuntu images block them);
- points `srimant-demo.duckdns.org` at the VM and keeps it pointed there every 10 minutes;
- starts the demo behind **Caddy**, which gets and renews a free Let's Encrypt certificate;
- schedules a **nightly backup and reset at 02:30 IST**. The story is restored, and the passwords you handed out keep working.

It prints the address. The accounts are in `~/thodara/demo-accounts.txt` on the VM.

### Day to day (on the VM, in `~/thodara`)

| Command | Does |
|---|---|
| `scripts/demo.sh url` | Shows the address |
| `cat demo-accounts.txt` | Shows the accounts |
| `scripts/demo.sh reset` | Restores the story now, same passwords |
| `scripts/demo.sh new-passwords` | Restores the story with new passwords (old ones stop working) |
| `scripts/demo.sh backup` | Saves a database copy in `backups/` (the newest 14 are kept) |
| `scripts/demo.sh status` / `stop` / `start` | Shows, stops or starts the demo |
| `git pull && scripts/demo.sh start` | Updates to the latest Thodara |

### Good to know

- **Idle servers.** Oracle may reclaim an Always Free VM that stays almost idle (under 20% use) for 7 days. A demo between visits is mostly idle. We do not run artificial load to avoid this. If it happens, create a new VM and run the setup script again (about 20 minutes): the demo data is reloaded and nothing real is lost. Oracle describes reclamation as a Free Tier account rule. Upgrading the account to Pay As You Go is reported to avoid it, but then anything beyond the free allowance is charged. That is your decision.
- **Fictional data only.** The nightly reset deletes anything visitors typed in. Don't use this server for a pilot.
- **Login limits** count each visitor separately (Caddy passes the visitor's real address). HTTP is redirected to HTTPS.

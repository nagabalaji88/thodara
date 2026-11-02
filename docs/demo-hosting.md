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

## Option B: always-on Oracle Cloud free server (next slice, D2)

Planned:

- An Oracle Cloud "Always Free" VM in Mumbai or Hyderabad running the same `scripts/demo.sh`.
- A fixed address with automatic HTTPS.
- A nightly reset and backup.
- A small keep-alive so Oracle does not reclaim the idle VM.

Account sign-up needs a card for verification; the free allowance is not charged.

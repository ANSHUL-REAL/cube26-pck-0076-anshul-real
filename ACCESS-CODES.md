# Access codes

Pack Manager signs people in with an access code instead of a username and password. A code picks the **company** (organisation) and the **operator label** stamped on every check and override. Why codes and not accounts: see [README › Sign-in](README.md#sign-in-why-access-codes-not-accounts).

Live demo: **https://pack-manager-lzht.onrender.com/login**

## Public demo codes

These are public on purpose, for judges and other tracks. Anyone with this page can use them, so **never put real orders or photos under them**.

| Code | Company | Operator label | Use it for |
|---|---|---|---|
| `alpha-demo` | Alpha Outfitters (demo) | `op_alpha` | The one-click demo on the sign-in page |
| `alpha-packer-1` | Alpha Outfitters (demo) | `packer_1` | A packing station |
| `alpha-packer-2` | Alpha Outfitters (demo) | `packer_2` | A second station, to see two people in one company's history |
| `alpha-lead` | Alpha Outfitters (demo) | `team_lead` | Reviewing and overriding checks |
| `alpha-judge` | Alpha Outfitters (demo) | `judge` | Judges, so their checks are easy to find in Records |
| `bravo-demo` | Bravo Supplies (demo) | `op_bravo` | The one-click demo on the sign-in page |
| `bravo-packer-1` | Bravo Supplies (demo) | `packer_1` | A packing station |
| `bravo-lead` | Bravo Supplies (demo) | `team_lead` | Reviewing and overriding checks |
| `bravo-judge` | Bravo Supplies (demo) | `judge` | Judges, second company |

**Try the separation:** sign in as `alpha-judge`, check a box, then sign in as `bravo-judge`. Bravo can't see Alpha's orders, records or photos, and opening an Alpha record's address from Bravo returns "not found". The database enforces this, not the app.

## For programs (Returns, Recovery)

The same codes work on the records API in the `X-Access-Code` header:

```bash
curl -H "X-Access-Code: alpha-demo" https://pack-manager-lzht.onrender.com/v1/records
```

See [contract/README.md](contract/README.md) for the endpoints.

## Limits

- Each demo company can run **60 agent checks a day**, shared by all its codes, to protect the free model key. After that, photos and records are still saved, and a person decides.
- A code identifies a station or role, not a verified person, and codes don't expire.

## How codes are stored and added

- The database stores only each code's SHA-256, in a table the app's role can't read. One `SECURITY DEFINER` function answers "which company and operator is this?" for an exact match.
- The codes are listed in `app/migrate.py` (`DEMO_CODES`, `STATION_CODES`). To add or rename one without touching orders or records:

```bash
python -m app.migrate --codes-only
```

- A real deployment would issue private codes per company, not ones written in the repository.

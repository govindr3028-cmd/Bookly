# Bookly (Django)

Member registration with email OTP verification, login/logout, a Bootstrap 5 member dashboard,
and Book / Loan CRUD with role-based access.

## Run it
```bash
python -m venv venv && source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt
python manage.py migrate
python manage.py createsuperuser                      # superusers are staff -> can manage books & loans
python manage.py runserver
```
Open http://127.0.0.1:8000/ . Run tests with `python manage.py test`.

## Verification emails (important)
Bookly sends the OTP over SMTP as soon as credentials exist:
1. Copy `.env.example` to `.env` (next to `manage.py`).
2. Fill `EMAIL_HOST_USER` and `EMAIL_HOST_PASSWORD`. For Gmail use an **App password**
   (Google Account -> Security -> 2-Step Verification -> App passwords), not your normal password.
3. Restart the server. Check delivery with `python manage.py sendtestemail you@example.com`.

Without credentials nothing can be delivered, so in development (`DEBUG=1`) the code is shown on the
verify page instead. That fallback switches off automatically once SMTP is configured or `DEBUG=0`.

## Roles
| Action | Member | Staff (`is_staff`) |
|---|---|---|
| Browse / search books, borrow an available book | yes | yes |
| View own loans / loan detail | yes (own only; others 404) | all loans |
| Add / edit / delete books | no (403) | yes |
| Issue / edit / delete loans, mark returned | no (403) | yes |

To make a member staff: Django admin (`/admin/`) -> Users -> tick "Staff status".

## Key rules
- OTP: 6 digits from `secrets`, stored only as a keyed hash, expires in 10 min, 5 wrong tries max, 60 s resend cooldown.
- Unverified users who enter correct credentials are not logged in; a new OTP is sent and they go to the verify page.
- Availability = `total_copies` − unreturned loans. Enforced in `Loan.clean()` (inside a transaction with a row lock),
  plus a DB constraint preventing the same member holding two open copies of one book.
- Limits (`settings.py`): 14-day loan period, 5 active loans per member.

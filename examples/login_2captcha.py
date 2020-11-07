from twocaptcha import TwoCaptcha
import rockblox
import secrets

# initialize solver(2captcha) and rockblox session
solver = TwoCaptcha("API_KEY")
session = rockblox.Session()

# wait for captcha result
captcha_result = solver.funcaptcha(
    sitekey="9F35E182-C93C-EBCC-A31D-CF8ED317B996",
    url=session.build_url("www", "/login"))

# login credentials
credential_type = "Username"
credential = "burger9234"
password = "burger123"

# login attempt
session.login(
    credential,
    password,
    credential_type,
    captcha_token=captcha_result["code"],
    captcha_provider="PROVIDER_ARKOSE_LABS")

# print user name and id
print(session.name, session.id)
import os
import tempfile

# 测试强制走 MOCK（不烧 key、结果确定）；用临时数据库，不污染 app.db。
os.environ["MOCK"] = "1"
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="qb_test_"), "test.db")
os.environ.setdefault("SILICONFLOW_API_KEY", "")
# 测试不发真短信：先占住这些变量，load_dotenv 就不会用 .env 里的值覆盖
for _key in (
    "ALIYUN_ACCESS_KEY_ID",
    "ALIYUN_ACCESS_KEY_SECRET",
    "ALIBABA_CLOUD_ACCESS_KEY_ID",
    "ALIBABA_CLOUD_ACCESS_KEY_SECRET",
    "SMS_SIGN_NAME",
    "SMS_TEMPLATE_CODE",
):
    os.environ[_key] = ""

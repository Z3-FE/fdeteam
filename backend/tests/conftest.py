import os
import tempfile

# 测试强制走 MOCK（不烧 key、结果确定）；用临时数据库，不污染 app.db。
os.environ["MOCK"] = "1"
os.environ["DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="qb_test_"), "test.db")
os.environ.setdefault("SILICONFLOW_API_KEY", "")

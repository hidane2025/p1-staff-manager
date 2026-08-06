"""P1 Staff Manager — DBアクセス層（互換窓口）

2026-08-06 リファクタリング: 実体は dbx/ パッケージへ分割した（挙動不変）。
呼び出し側は従来どおり `import db` → `db.関数()` を使えばよい。
分割の狙い: 1,822行の単一ファイルで衝突・見通し悪化が起きていたため、
ドメイン別（core/staff/events/shifts/transport/payments/auth）に整理した。

テストで接続先を差し替える場合は dbx.core.get_client を差し替えること
（test_e2e/_fake_db.py が対応済み）。
"""

from dbx.core import *  # noqa: F401,F403
from dbx.staff import *  # noqa: F401,F403
from dbx.transport import *  # noqa: F401,F403
from dbx.events import *  # noqa: F401,F403
from dbx.shifts import *  # noqa: F401,F403
from dbx.auth import *  # noqa: F401,F403
from dbx.payments import *  # noqa: F401,F403

# 外部から参照されている内部ヘルパーの互換維持
from dbx.staff import (  # noqa: F401  (test_e2e/23 名寄せテスト)
    _norm_key, _build_staff_index, _match_staff, _index_add,
)
from dbx.payments import _allowance_default_label  # noqa: F401  (pages/11)
from dbx.shifts import _validate_lunch_status  # noqa: F401  (test_e2e/24)
from dbx.core import _now  # noqa: F401

"""Live-коннекторы (doc 02 §1.2): SFTP-monitor и SQL-CDR на фейк-транспортах —
без сети. SFTP: DI connect_factory с in-memory файлами; SQL: sqlite с cdr."""

from datetime import datetime, timedelta

from sqlalchemy import Column, DateTime, Integer, MetaData, String, Table, insert

from polylog.ingest.base import ConnectorError
from polylog.ingest.live import SftpConfig, SftpFileSource, SftpMonitorConnector, SqlCdrSource
from polylog.ingest.registry import get_connector


class FakeSftpClient:
    """paramiko-подобный клиент над словарём {name: (bytes, mtime)}."""

    def __init__(self, files: dict[str, tuple[bytes, float]]) -> None:
        self.files = files

    def open_sftp(self):
        return self

    def listdir(self, path):  # для verify
        return list(self.files)

    def listdir_attr(self, path):
        class E:
            def __init__(self, name, mtime, size):
                self.filename, self.st_mtime, self.st_size = name, mtime, size

        return [E(n, m, len(b)) for n, (b, m) in self.files.items()]

    def open(self, path, mode="rb"):
        import io

        name = str(path).rsplit("/", 1)[-1]
        return io.BytesIO(self.files[name][0])


def test_sftp_connector_discover_and_download():
    files = {
        "q-101-+79001112233-20261007-in.wav": (b"RIFF....", datetime(2026, 10, 7, 10, 0).timestamp()),
        "q-101-+79004445566-20261008-out.wav": (b"RIFF....", datetime(2026, 10, 8, 11, 0).timestamp()),
        "notes.txt": (b"x", datetime(2026, 10, 8, 12, 0).timestamp()),  # не *.wav
    }
    cfg = SftpConfig(host="pbx", username="u", remote_dir="/monitor", pattern="*.wav")
    src = SftpFileSource(cfg, connect_factory=lambda: FakeSftpClient(files))
    conn = SftpMonitorConnector(cfg)
    conn.source = src

    assert conn.verify()["ok"] is True

    since = datetime(2026, 10, 7, 12, 0)
    refs = conn.discover(since)
    assert [r.external_id.rsplit(":", 1)[1] for r in refs] == [
        "q-101-+79004445566-20261008-out.wav"
    ]
    ref = refs[0]
    assert ref.direction == "outbound"
    assert ref.phone_to == "+79004445566"
    assert ref.phone_from is None

    data = conn.download(ref)
    assert data == b"RIFF...."

    # все файлы (без since) → оба wav, направление по суффиксу -in
    refs_all = conn.discover(datetime(2000, 1, 1))
    directions = {r.external_id: r.direction for r in refs_all}
    assert directions["sftp-monitor:q-101-+79001112233-20261007-in.wav"] == "inbound"
    inbound = next(r for r in refs_all if r.direction == "inbound")
    assert inbound.phone_from == "+79001112233"


def test_sftp_registry_and_verify_error():
    conn = get_connector("sftp-monitor", {"host": "h", "username": "u"})
    assert conn.id == "sftp-monitor"
    # фейковый транспорт с ошибкой → verify.ok False, а не исключение
    def broken():
        raise ConnectionError("refused")

    conn.source = SftpFileSource(conn.config, connect_factory=broken)
    v = conn.verify()
    assert v["ok"] is False and "refused" in v["error"]

    # без кредов коннектор создаётся, download без recording_uri — ошибка
    try:
        conn.download(ref=None.recording_uri and None)  # type: ignore[arg-type]
        raised = False
    except (ConnectorError, AttributeError):
        raised = True
    assert raised


def test_sql_cdr_source_sqlite(tmp_path):
    """SQL-CDR: sqlite с таблицей cdr → discover с ролями по коротким номерам."""
    md = MetaData()
    cdr = Table(
        "cdr", md,
        Column("uniqueid", String(64)),
        Column("calldate", DateTime()),
        Column("src", String(64)),
        Column("dst", String(64)),
        Column("duration", Integer),
        Column("billsec", Integer),
        Column("disposition", String(32)),
    )
    engine_url = f"sqlite:///{tmp_path}/cdr.db"
    from sqlalchemy import create_engine

    eng = create_engine(engine_url)
    md.create_all(eng)
    base = datetime(2026, 10, 7, 9, 0)
    with eng.begin() as c:
        c.execute(insert(cdr).values([
            dict(uniqueid="u1", calldate=base, src="+79001112233", dst="101",
                 duration=120, billsec=100, disposition="ANSWERED"),
            dict(uniqueid="u2", calldate=base + timedelta(hours=2), src="102",
                 dst="+79005554433", duration=60, billsec=50, disposition="ANSWERED"),
            dict(uniqueid="old", calldate=base - timedelta(days=5), src="1", dst="2",
                 duration=5, billsec=1, disposition="NO ANSWER"),
        ]))

    src = SqlCdrSource(engine_url)
    assert src.verify()["ok"] is True

    refs = src.discover(base - timedelta(minutes=1))
    assert [r.external_id for r in refs] == ["sql-cdr:u1", "sql-cdr:u2"]

    r1 = refs[0]  # входящий: клиент звонит на внутренний 101
    assert r1.direction == "inbound"
    assert r1.phone_from == "+79001112233" and r1.phone_to == "101"
    assert r1.agent_ext == "101" and r1.duration_sec == 120

    r2 = refs[1]  # исходящий: 102 звонит клиенту
    assert r2.direction == "outbound"
    assert r2.phone_to == "+79005554433" and r2.phone_from == "102"

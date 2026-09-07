import seed_accounts
from src import db


def test_load_seeds_inserts_accounts(tmp_path):
    seeds = tmp_path / "seeds.txt"
    seeds.write_text(
        "# wine\n"
        "wineexample, wine\n"
        "winememequeen, wine memes\n"
        "\n"
        "serverproblems, hospitality\n"
    )
    db_path = str(tmp_path / "t.db")
    count = seed_accounts.load_seeds(str(seeds), db_path)
    assert count == 3

    conn = db.connect(db_path)
    rows = {r["username"]: r["category"] for r in db.get_active_accounts(conn)}
    assert rows["winememequeen"] == "wine memes"
    assert "#" not in "".join(rows)
    conn.close()


def test_load_seeds_is_rerunnable(tmp_path):
    seeds = tmp_path / "seeds.txt"
    seeds.write_text("wineexample, wine\n")
    db_path = str(tmp_path / "t.db")
    seed_accounts.load_seeds(str(seeds), db_path)
    seed_accounts.load_seeds(str(seeds), db_path)
    conn = db.connect(db_path)
    assert len(db.get_active_accounts(conn)) == 1
    conn.close()


def test_reseeding_does_not_reactivate_deactivated_accounts(tmp_path):
    """discover.py deactivates accounts that stopped fitting; re-running the
    seeder must not silently undo that."""
    seeds = tmp_path / "seeds.txt"
    seeds.write_text("wineexample, wine\n")
    db_path = str(tmp_path / "t.db")
    seed_accounts.load_seeds(str(seeds), db_path)

    conn = db.connect(db_path)
    db.upsert_account(conn, "wineexample", active=0)
    conn.close()

    seed_accounts.load_seeds(str(seeds), db_path)

    conn = db.connect(db_path)
    row = conn.execute("SELECT active FROM accounts WHERE username = ?",
                       ("wineexample",)).fetchone()
    conn.close()
    assert row["active"] == 0

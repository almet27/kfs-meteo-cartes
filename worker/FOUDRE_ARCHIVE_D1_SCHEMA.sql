-- KFS MÉTÉO : archive courte des relevés de foudre Xweather
-- À exécuter une fois dans la console Cloudflare D1 (base liée FOUDRE_DB).
-- Aucune clé API, donnée d'identification personnelle ni secret dans ce fichier.

CREATE TABLE IF NOT EXISTS foudre_archive_snapshots (
  zone TEXT NOT NULL,
  slot INTEGER NOT NULL,
  poll_at INTEGER NOT NULL,
  status TEXT NOT NULL,
  source_count INTEGER NOT NULL DEFAULT 0,
  events_json TEXT NOT NULL DEFAULT '[]',
  PRIMARY KEY (zone, slot)
);
CREATE INDEX IF NOT EXISTS foudre_archive_poll_at
  ON foudre_archive_snapshots(poll_at);

CREATE TABLE IF NOT EXISTS foudre_archive_usage (
  month TEXT PRIMARY KEY,
  requests INTEGER NOT NULL DEFAULT 0
    CHECK (requests >= 0)
);

-- Ne conserver que les relevés récents.
-- Un nettoyage équivalent est exécuté par le Worker à chaque cron de 2 min.
DELETE FROM foudre_archive_snapshots
WHERE poll_at < CAST(strftime('%s','now') AS INTEGER)-2160;

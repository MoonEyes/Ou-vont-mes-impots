-- Table du comptage anonyme (docs/AUDIENCE.md). Le Worker la crée seul au premier passage ;
-- ce fichier sert à la créer à la main si besoin (console D1 du tableau de bord).
CREATE TABLE IF NOT EXISTS visites (
  jour TEXT NOT NULL,
  chemin TEXT NOT NULL,
  pays TEXT NOT NULL,
  referent TEXT NOT NULL,
  appareil TEXT NOT NULL,
  robot INTEGER NOT NULL,
  vues INTEGER NOT NULL DEFAULT 0,
  PRIMARY KEY (jour, chemin, pays, referent, appareil, robot)
) WITHOUT ROWID;

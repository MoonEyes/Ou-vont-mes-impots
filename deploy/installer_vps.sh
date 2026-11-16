#!/usr/bin/env bash
# Installation de la collecte hebdomadaire sur un VPS Debian/Ubuntu (a lancer en root, relancable) :
#   curl -fsSLO https://raw.githubusercontent.com/MoonEyes/Ou-vont-mes-impots/main/deploy/installer_vps.sh
#   sudo bash installer_vps.sh
# Fait : utilisateur systeme « ovmi » sans shell ni sudo, depot public clone dans /var/lib/ovmi,
# venv Python (requirements + duckdb + xlrd), rclone officiel (somme SHA256 verifiee), extension
# DuckDB httpfs, /etc/ovmi/stockage.env (modele vide, 640 root:ovmi), unites systemd + minuterie.
# Ne fait pas : saisir des cles (a mettre dans /etc/ovmi/stockage.env), lancer une collecte.
set -euo pipefail

UTILISATEUR=${OVMI_UTILISATEUR:-ovmi}
RACINE=${OVMI_RACINE:-/var/lib/ovmi}
DEPOT_URL=${OVMI_DEPOT_URL:-https://github.com/MoonEyes/Ou-vont-mes-impots.git}
BRANCHE=${OVMI_BRANCHE:-main}
DEPOT=$RACINE/ou-vont-mes-impots
CONF=/etc/ovmi

die() { echo "ERREUR : $*" >&2; exit 1; }
etape() { echo; echo "==> $*"; }
en_ovmi() { runuser -u "$UTILISATEUR" -- env HOME="$RACINE" "$@"; }

[[ $(id -u) -eq 0 ]] || die "a lancer en root (sudo bash $0)"
command -v apt-get >/dev/null || die "Debian ou Ubuntu attendu (apt-get)"

etape "paquets systeme"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq --no-install-recommends python3 python3-venv python3-pip git curl unzip \
    ca-certificates util-linux coreutils >/dev/null

etape "utilisateur dedie $UTILISATEUR (sans shell, sans sudo)"
if ! id -u "$UTILISATEUR" >/dev/null 2>&1; then
    useradd --system --home-dir "$RACINE" --create-home --shell /usr/sbin/nologin \
        --comment "Ou vont mes impots, collecte" "$UTILISATEUR"
fi
install -d -m 750 -o "$UTILISATEUR" -g "$UTILISATEUR" "$RACINE" "$RACINE/journaux"

etape "rclone (binaire officiel, somme SHA256 verifiee)"
case "$(uname -m)" in
    x86_64) ARCH=amd64 ;;
    aarch64|arm64) ARCH=arm64 ;;
    *) die "architecture non geree : $(uname -m)" ;;
esac
VERSION=$(curl -fsSL https://downloads.rclone.org/version.txt | awk '{print $2}')
[[ $VERSION =~ ^v[0-9]+\.[0-9]+\.[0-9]+$ ]] || die "version rclone illisible : $VERSION"
ACTUELLE=$(rclone version 2>/dev/null | awk 'NR==1 {print $2}' || true)
if [[ "$ACTUELLE" != "$VERSION" ]]; then
    TMP=$(mktemp -d)
    trap 'rm -rf "$TMP"' EXIT
    ZIP=rclone-$VERSION-linux-$ARCH.zip
    curl -fsSL -o "$TMP/$ZIP" "https://downloads.rclone.org/$VERSION/$ZIP"
    curl -fsSL -o "$TMP/SHA256SUMS" "https://downloads.rclone.org/$VERSION/SHA256SUMS"
    (cd "$TMP" && grep " $ZIP\$" SHA256SUMS | sha256sum -c -) || die "somme SHA256 de rclone invalide"
    unzip -q -o "$TMP/$ZIP" -d "$TMP"
    install -m 755 "$TMP/rclone-$VERSION-linux-$ARCH/rclone" /usr/local/bin/rclone
fi
rclone version | head -1

etape "depot $DEPOT_URL ($BRANCHE)"
if [[ -d "$DEPOT/.git" ]]; then
    en_ovmi git -C "$DEPOT" pull --ff-only -q
else
    en_ovmi git clone -q --branch "$BRANCHE" --depth 50 "$DEPOT_URL" "$DEPOT"
fi
chmod 750 "$DEPOT"

etape "environnement Python"
[[ -x "$RACINE/venv/bin/python" ]] || en_ovmi python3 -m venv "$RACINE/venv"
en_ovmi "$RACINE/venv/bin/pip" install -q --upgrade pip
en_ovmi "$RACINE/venv/bin/pip" install -q -r "$DEPOT/requirements.txt" -r "$DEPOT/deploy/requirements-vps.txt"
en_ovmi "$RACINE/venv/bin/python" -c "import duckdb; duckdb.sql('INSTALL httpfs'); print('duckdb', duckdb.__version__)"

etape "configuration $CONF/stockage.env"
install -d -m 750 -o root -g "$UTILISATEUR" "$CONF"
if [[ ! -f "$CONF/stockage.env" ]]; then
    install -m 640 -o root -g "$UTILISATEUR" "$DEPOT/deploy/env.exemple" "$CONF/stockage.env"
    echo "modele copie : a completer (cles S3 et noms des buckets)"
else
    chown root:"$UTILISATEUR" "$CONF/stockage.env"; chmod 640 "$CONF/stockage.env"
    echo "deja present, conserve"
fi

etape "unites systemd"
install -m 644 "$DEPOT"/deploy/systemd/ovmi-collecte.service "$DEPOT"/deploy/systemd/ovmi-collecte.timer \
    "$DEPOT"/deploy/systemd/ovmi-collecte-alerte.service /etc/systemd/system/
chmod 755 "$DEPOT/deploy/collecte-hebdo.sh"
systemctl daemon-reload
systemctl enable --now ovmi-collecte.timer
systemctl list-timers ovmi-collecte.timer --no-pager | head -3

cat <<FIN

Installation terminee. Etapes suivantes :
  1. sudo nano $CONF/stockage.env      (cles S3 OVH, OVMI_BUCKET_PUBLIC, OVMI_BUCKET_PRIVE)
  2. sudo -u $UTILISATEUR bash -c 'set -a; . $CONF/stockage.env; cd $DEPOT && $RACINE/venv/bin/python collecte/stockage.py config'
  3. premier passage a la main (sinon lundi 3 h) : sudo systemctl start ovmi-collecte.service
     suivi : journalctl -u ovmi-collecte -f
FIN

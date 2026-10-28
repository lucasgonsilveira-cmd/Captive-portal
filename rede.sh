#!/bin/bash
# ============================================================================
# REDE.SH — sobe (ou derruba) o hotspot inteiro na ordem certa
# ============================================================================
# Uso:  sudo ./rede.sh start | stop | status
# Faz: libera o rfkill, tira o Wi-Fi do NetworkManager, define o IP fixo,
#      inicia hostapd + dnsmasq e aplica o firewall.sh.
# O app.py (Flask) é iniciado à parte: sudo python3 app.py
# ============================================================================
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
set -a; . "$DIR/config.env"; set +a
RUN=/run/portal

[ "$(id -u)" -eq 0 ] || { echo "Rode com sudo."; exit 1; }

matar() {  # $1 = arquivo de PID
  [ -f "$1" ] && kill "$(cat "$1")" 2>/dev/null
  rm -f "$1"
  return 0
}

parar() {
  matar "$RUN/hostapd.pid"
  matar "$RUN/dnsmasq.pid"
  iptables -F; iptables -t nat -F
  iptables -X 2>/dev/null; iptables -t nat -X 2>/dev/null
  iptables -P FORWARD ACCEPT
  ip addr flush dev "$AP_IF" 2>/dev/null
  return 0
}

conferir_config() {
  ip link show "$AP_IF" >/dev/null 2>&1 \
    || { echo "ERRO: interface $AP_IF não existe. Veja as interfaces com: ip -br link"; exit 1; }
  ip link show "$UP_IF" >/dev/null 2>&1 \
    || echo "AVISO: interface $UP_IF não existe — o portal sobe, mas sem internet para liberar."
  grep -q "^interface=$AP_IF\$" "$DIR/hostapd.conf" \
    || { echo "ERRO: 'interface=' do hostapd.conf diferente de AP_IF=$AP_IF"; exit 1; }
  grep -q "^interface=$AP_IF\$" "$DIR/dnsmasq.conf" \
    || { echo "ERRO: 'interface=' do dnsmasq.conf diferente de AP_IF=$AP_IF"; exit 1; }
  grep -q "^listen-address=$PORTAL_IP\$" "$DIR/dnsmasq.conf" \
    || { echo "ERRO: 'listen-address=' do dnsmasq.conf diferente de PORTAL_IP=$PORTAL_IP"; exit 1; }
}

iniciar() {
  conferir_config
  mkdir -p "$RUN"

  rfkill unblock wifi 2>/dev/null || true
  if command -v nmcli >/dev/null 2>&1; then
    nmcli device set "$AP_IF" managed no 2>/dev/null || true
  fi
  systemctl stop dnsmasq 2>/dev/null || true   # serviço padrão do Debian conflitaria na porta 53

  parar
  ip link set "$AP_IF" up
  ip addr add "$PORTAL_IP/24" dev "$AP_IF"

  echo ">> hostapd"
  hostapd -B -P "$RUN/hostapd.pid" "$DIR/hostapd.conf" \
    || { echo "ERRO: hostapd não subiu. Rode 'sudo hostapd -d $DIR/hostapd.conf' para ver o motivo."; exit 1; }
  sleep 2

  echo ">> dnsmasq"
  dnsmasq --conf-file="$DIR/dnsmasq.conf" \
    || { echo "ERRO: dnsmasq não subiu (porta 53 ocupada?). Veja: sudo ss -lunp | grep :53"; exit 1; }

  echo ">> firewall"
  "$DIR/firewall.sh" || exit 1

  echo
  echo "Hotspot no ar. Agora inicie o portal:  sudo python3 $DIR/app.py"
}

status() {
  echo "--- interface do hotspot"; ip -br addr show "$AP_IF"
  iw dev "$AP_IF" info 2>/dev/null | grep -E "ssid|type|channel"
  echo "--- processos"
  for p in hostapd dnsmasq; do
    if [ -f "$RUN/$p.pid" ] && kill -0 "$(cat "$RUN/$p.pid")" 2>/dev/null; then echo "$p: rodando"; else echo "$p: PARADO"; fi
  done
  echo "--- aparelhos com IP (DHCP)"; cat "$RUN/dnsmasq.leases" 2>/dev/null
  echo "--- MACs liberados"; iptables -S PORTAL_OK 2>/dev/null | grep -- '--mac-source' || echo "(nenhum)"
}

case "$1" in
  start)  iniciar ;;
  stop)   parar; echo "Hotspot parado e firewall liberado." ;;
  status) status ;;
  *) echo "Uso: sudo $0 start|stop|status"; exit 1 ;;
esac

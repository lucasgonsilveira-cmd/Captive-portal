#!/bin/bash
# ============================================================================
# FIREWALL.SH — regras do portal cativo
# ============================================================================
# Uso: sudo ./firewall.sh        (lê AP_IF, UP_IF e PORTAL_IP do config.env)
# Normalmente quem chama é o rede.sh.
#
# Como funciona (o app.py só mexe nas duas correntes "PORTAL_OK*"):
#   - Todo mundo que entra no hotspot começa BLOQUEADO.
#   - Porta 80 de quem está bloqueado é desviada para o portal (DNAT).
#   - Quando o visitante clica em "Liberar acesso", o app.py acrescenta o MAC dele
#     em PORTAL_OK (filter) e em PORTAL_OK_NAT (nat). A partir daí ele navega
#     direto, sem desvio.
# ============================================================================
set -e
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
set -a; . "$DIR/config.env"; set +a

echo "Firewall: hotspot=$AP_IF  internet=$UP_IF  portal=$PORTAL_IP"

# 1. Permite o kernel rotear entre as duas interfaces
sysctl -qw net.ipv4.ip_forward=1

# 2. Zera tudo e recria as correntes do portal
iptables -F
iptables -t nat -F
iptables -X 2>/dev/null || true
iptables -t nat -X 2>/dev/null || true
iptables -P INPUT ACCEPT
iptables -P OUTPUT ACCEPT
iptables -P FORWARD DROP

iptables -N PORTAL_OK                 # filter: 1 regra ACCEPT por MAC liberado
iptables -t nat -N PORTAL_OK_NAT      # nat:    1 regra ACCEPT por MAC liberado

# 3. INPUT — o que um visitante pode falar com o próprio TV box
#    (o SSH e o resto ficam fechados para o hotspot; use o cabo para administrar)
iptables -A INPUT -i "$AP_IF" -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
iptables -A INPUT -i "$AP_IF" -p udp --dport 67 -j ACCEPT      # DHCP
iptables -A INPUT -i "$AP_IF" -p udp --dport 53 -j ACCEPT      # DNS
iptables -A INPUT -i "$AP_IF" -p tcp --dport 53 -j ACCEPT
iptables -A INPUT -i "$AP_IF" -p tcp --dport 80 -j ACCEPT      # portal
iptables -A INPUT -i "$AP_IF" -p icmp -j ACCEPT
iptables -A INPUT -i "$AP_IF" -j DROP

# 4. FORWARD — o que passa do hotspot para a internet
#    4a. respostas de conexões já permitidas (SEM esta regra a internet "vai"
#        mas a resposta nunca volta — era o que faltava na versão anterior)
iptables -A FORWARD -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
#    4b. MACs liberados pelo app.py
iptables -A FORWARD -i "$AP_IF" -o "$UP_IF" -j PORTAL_OK
#    4c. o resto é recusado NA HORA (em vez de ficar travado até dar timeout)
iptables -A FORWARD -i "$AP_IF" -p tcp -j REJECT --reject-with tcp-reset
iptables -A FORWARD -i "$AP_IF" -j REJECT --reject-with icmp-port-unreachable

# 5. NAT
iptables -t nat -A POSTROUTING -o "$UP_IF" -j MASQUERADE
#    MACs liberados passam direto (sem desvio de porta 80)
iptables -t nat -A PREROUTING -i "$AP_IF" -j PORTAL_OK_NAT
#    Quem não foi liberado: todo HTTP vai para o portal
iptables -t nat -A PREROUTING -i "$AP_IF" -p tcp --dport 80 \
  -j DNAT --to-destination "$PORTAL_IP:80"

echo "Firewall pronto. Visitantes só veem o portal até clicarem em 'Liberar acesso'."

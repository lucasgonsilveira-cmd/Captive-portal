#!/usr/bin/env python3
"""
============================================================================
PORTAL CATIVO - FATEC JAHU  (backend Flask + MariaDB)
============================================================================
O que este servidor faz:

  1. Serve a página do portal (portal-fatec-jahu.html) e responde às
     "perguntas de internet" que celulares e PCs fazem ao conectar
     (/generate_204, /hotspot-detect.html ...). É isso que faz a janela do
     portal abrir sozinha no celular.
  2. Registra no MariaDB o que o visitante faz (abriu curso, tenho interesse,
     liberou) — sempre de forma anônima (hash do MAC).
  3. Login opcional por RA (só RAs previamente cadastrados na tabela `alunos`),
     que mostra avisos e horários de aula.
  4. Libera o visitante: acrescenta o MAC dele nas correntes PORTAL_OK e
     PORTAL_OK_NAT criadas pelo firewall.sh, e remove sozinho depois de
     SESSAO_MINUTOS.
  5. Relatórios para o TCC em /admin/relatorio e /admin/eventos.csv
     (só de fora do hotspot e com ADMIN_TOKEN).

Como rodar (depois de: sudo ./rede.sh start):
    sudo python3 app.py
============================================================================
"""
import csv
import hashlib
import hmac
import html
import io
import ipaddress
import json
import os
import re
import subprocess
import threading
import time
from datetime import datetime
from pathlib import Path

import pymysql
from flask import Flask, Response, jsonify, redirect, request, send_from_directory

BASE = Path(__file__).resolve().parent


# ----------------------------------------------------------------------
# CONFIGURAÇÃO (lida do config.env; variáveis de ambiente têm prioridade)
# ----------------------------------------------------------------------
def carregar_config():
    arquivo = BASE / "config.env"
    if not arquivo.exists():
        return
    for linha in arquivo.read_text(encoding="utf-8").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip())


carregar_config()

AP_IF = os.environ.get("AP_IF", "wlan0")
PORTAL_IP = os.environ.get("PORTAL_IP", "192.168.50.1")
SESSAO_MINUTOS = int(os.environ.get("SESSAO_MINUTOS", "120"))
DB_HOST = os.environ.get("DB_HOST", "127.0.0.1")
DB_USER = os.environ.get("DB_USER", "portal")
DB_PASS = os.environ.get("DB_PASS", "")
DB_NAME = os.environ.get("DB_NAME", "portal_fatec")
SALT = os.environ.get("SALT", "")
ADMIN_TOKEN = os.environ.get("ADMIN_TOKEN", "")

NOME_ARQUIVO_PORTAL = "portal-fatec-jahu.html"
REDE_HOTSPOT = ipaddress.ip_network(f"{PORTAL_IP}/24", strict=False)
# Se o banco cair no meio do evento, os eventos vão para este arquivo (nada se perde).
ARQUIVO_RESERVA = BASE / "eventos_pendentes.jsonl"

app = Flask(__name__)


# ----------------------------------------------------------------------
# IDENTIFICAÇÃO DO VISITANTE (IP -> MAC)
# ----------------------------------------------------------------------
RE_MAC = re.compile(r"lladdr ((?:[0-9a-f]{2}:){5}[0-9a-f]{2})", re.I)


def mac_do_ip(ip):
    """Descobre o MAC de um IP do hotspot na tabela de vizinhos do kernel."""
    try:
        saida = subprocess.run(
            ["ip", "-4", "neigh", "show", "to", ip, "dev", AP_IF],
            capture_output=True, text=True, timeout=3,
        ).stdout
    except Exception:
        return None
    achou = RE_MAC.search(saida)
    return achou.group(1).lower() if achou else None


def cliente():
    """(ip, mac) de quem fez a requisição. mac pode ser None."""
    ip = request.remote_addr or ""
    try:
        if ipaddress.ip_address(ip) not in REDE_HOTSPOT:
            return ip, None
    except ValueError:
        return ip, None
    return ip, mac_do_ip(ip)


def hash_mac(identidade):
    """Hash com segredo (SALT): o banco nunca guarda o MAC real."""
    return hmac.new(SALT.encode(), identidade.encode(), hashlib.sha256).hexdigest()


def identidade(ip, mac):
    return mac or f"ip-{ip}"


# ----------------------------------------------------------------------
# BANCO DE DADOS
# ----------------------------------------------------------------------
def db():
    return pymysql.connect(
        host=DB_HOST, user=DB_USER, password=DB_PASS, database=DB_NAME,
        charset="utf8mb4", autocommit=True, connect_timeout=3,
        cursorclass=pymysql.cursors.DictCursor,
    )


def guardar_reserva(registro):
    try:
        with open(ARQUIVO_RESERVA, "a", encoding="utf-8") as f:
            f.write(json.dumps(registro, ensure_ascii=False) + "\n")
    except OSError as erro:
        print(f"[ERRO GRAVE] nem o arquivo de reserva funcionou: {erro}")


def registrar_evento(ident, tipo, curso=None):
    """Grava um evento anônimo. Nunca derruba a requisição se o banco falhar."""
    h = hash_mac(ident)
    con = None
    try:
        con = db()
        with con.cursor() as cur:
            cur.execute(
                "INSERT INTO dispositivos (mac_hash) VALUES (%s) "
                "ON DUPLICATE KEY UPDATE ultimo_acesso = CURRENT_TIMESTAMP",
                (h,),
            )
            cur.execute(
                "INSERT INTO eventos (dispositivo_id, tipo, curso_slug) "
                "SELECT id, %s, %s FROM dispositivos WHERE mac_hash = %s",
                (tipo, curso, h),
            )
        return True
    except Exception as erro:
        print(f"[banco] falha ao gravar evento ({tipo}): {erro}")
        guardar_reserva({"quando": datetime.now().isoformat(timespec="seconds"),
                         "mac_hash": h, "tipo": tipo, "curso": curso})
        return False
    finally:
        if con:
            con.close()


_cache_cursos = {"t": 0.0, "valores": set()}


def cursos_validos():
    if time.time() - _cache_cursos["t"] > 60:
        _cache_cursos["t"] = time.time()
        try:
            con = db()
            try:
                with con.cursor() as cur:
                    cur.execute("SELECT slug FROM cursos")
                    _cache_cursos["valores"] = {r["slug"] for r in cur.fetchall()}
            finally:
                con.close()
        except Exception as erro:
            print(f"[banco] não consegui ler cursos: {erro}")
    return _cache_cursos["valores"]


def curso_valido(slug):
    if not isinstance(slug, str) or not re.fullmatch(r"[a-z0-9_-]{1,10}", slug):
        return False
    conhecidos = cursos_validos()
    return (not conhecidos) or slug in conhecidos


def fmt_hora(valor):
    """O pymysql devolve TIME como timedelta; transforma em 'HH:MM'."""
    return (datetime.min + valor).strftime("%H:%M")


# ----------------------------------------------------------------------
# LIBERAÇÃO NO FIREWALL
# ----------------------------------------------------------------------
liberados = {}            # mac -> {"expira": epoch, "ip": ip}
trava = threading.Lock()


def _ipt(*args):
    subprocess.run(["iptables", *args], check=True, capture_output=True, text=True, timeout=5)


def _regras(mac, acao):
    """acao '-A' adiciona, '-D' remove, nas duas correntes do portal."""
    _ipt(acao, "PORTAL_OK", "-m", "mac", "--mac-source", mac, "-j", "ACCEPT")
    _ipt("-t", "nat", acao, "PORTAL_OK_NAT", "-m", "mac", "--mac-source", mac, "-j", "ACCEPT")


def liberar_mac(mac, ip):
    with trava:
        if mac not in liberados:
            _regras(mac, "-A")
        liberados[mac] = {"expira": time.time() + SESSAO_MINUTOS * 60, "ip": ip}


def revogar_mac(mac):
    with trava:
        info = liberados.pop(mac, None)
    if not info:
        return
    try:
        _regras(mac, "-D")
    except subprocess.CalledProcessError as erro:
        print(f"[erro] ao remover {mac}: {erro.stderr}")
    # corta conexões que ainda estejam abertas (precisa do pacote conntrack; opcional)
    try:
        subprocess.run(["conntrack", "-D", "-s", info["ip"]], capture_output=True, timeout=5)
    except Exception:
        pass


def esta_liberado(mac):
    with trava:
        info = liberados.get(mac)
        return bool(info) and info["expira"] > time.time()


def limpar_expirados():
    while True:
        time.sleep(30)
        agora = time.time()
        with trava:
            vencidos = [m for m, i in liberados.items() if i["expira"] <= agora]
        for mac in vencidos:
            revogar_mac(mac)
            print(f"[expirou] {mac} voltou para o portal")


def preparar_firewall():
    """Ao iniciar, esvazia as listas de liberados (o app começa sem ninguém liberado)."""
    try:
        _ipt("-F", "PORTAL_OK")
        _ipt("-t", "nat", "-F", "PORTAL_OK_NAT")
    except Exception as erro:
        print(f"[AVISO] correntes PORTAL_OK não existem. Rode antes: sudo ./rede.sh start ({erro})")


# ----------------------------------------------------------------------
# PORTAL E "DETECÇÃO DE INTERNET" DOS APARELHOS
# ----------------------------------------------------------------------
_ultima_abertura = {}


def redirecionar_para_portal():
    resposta = redirect(f"http://{PORTAL_IP}/", code=302)
    resposta.headers["Cache-Control"] = "no-store"
    return resposta


@app.route("/")
def portal():
    ip, mac = cliente()
    ident = identidade(ip, mac)
    # celulares abrem o portal várias vezes seguidas; conta 1 abertura a cada 10 min
    if time.time() - _ultima_abertura.get(ident, 0) > 600:
        _ultima_abertura[ident] = time.time()
        registrar_evento(ident, "abertura")
    resposta = send_from_directory(BASE, NOME_ARQUIVO_PORTAL)
    resposta.headers["Cache-Control"] = "no-store"
    return resposta


def resposta_deteccao(corpo, mimetipo="text/plain", status=200):
    """Liberado -> resposta que o aparelho espera quando TEM internet.
    Não liberado -> manda para o portal (é isso que abre a janela de login)."""
    _, mac = cliente()
    if mac and esta_liberado(mac):
        return Response(corpo, status=status, mimetype=mimetipo)
    return redirecionar_para_portal()


@app.route("/generate_204")          # Android
@app.route("/gen_204")
def android_204():
    return resposta_deteccao("", status=204)


@app.route("/hotspot-detect.html")   # iPhone / Mac
@app.route("/library/test/success.html")
def apple_success():
    return resposta_deteccao(
        "<HTML><HEAD><TITLE>Success</TITLE></HEAD><BODY>Success</BODY></HTML>", "text/html")


@app.route("/connecttest.txt")       # Windows
def windows_connecttest():
    return resposta_deteccao("Microsoft Connect Test")


@app.route("/success.txt")           # Firefox
def firefox_success():
    return resposta_deteccao("success\n")


# ----------------------------------------------------------------------
# API DO PORTAL
# ----------------------------------------------------------------------
@app.route("/api/avisos")
def api_avisos():
    """Avisos públicos (ex.: vestibular) mostrados para qualquer visitante."""
    try:
        con = db()
        try:
            with con.cursor() as cur:
                cur.execute(
                    "SELECT titulo, mensagem FROM avisos "
                    "WHERE ativo = 1 AND publico = 'todos' "
                    "AND (inicio IS NULL OR inicio <= NOW()) AND (fim IS NULL OR fim >= NOW()) "
                    "ORDER BY id DESC LIMIT 5")
                return jsonify({"ok": True, "avisos": cur.fetchall()})
        finally:
            con.close()
    except Exception as erro:
        print(f"[banco] avisos: {erro}")
        return jsonify({"ok": True, "avisos": []})


@app.route("/api/evento", methods=["POST"])
def api_evento():
    dados = request.get_json(silent=True) or {}
    tipo = dados.get("tipo")
    curso = dados.get("curso")
    if tipo not in ("ver_curso", "interesse") or not curso_valido(curso):
        return jsonify({"ok": False, "erro": "evento inválido"}), 400
    ip, mac = cliente()
    registrar_evento(identidade(ip, mac), tipo, curso)
    return jsonify({"ok": True})


_tentativas_login = {}


def login_bloqueado(ident):
    """No máximo 8 tentativas de RA a cada 10 minutos por aparelho."""
    agora = time.time()
    recentes = [t for t in _tentativas_login.get(ident, []) if agora - t < 600]
    recentes.append(agora)
    _tentativas_login[ident] = recentes
    return len(recentes) > 8


@app.route("/api/login", methods=["POST"])
def api_login():
    dados = request.get_json(silent=True) or {}
    ra = str(dados.get("ra", "")).strip().upper()
    ip, mac = cliente()
    ident = identidade(ip, mac)

    if login_bloqueado(ident):
        return jsonify({"ok": False, "erro": "Muitas tentativas. Aguarde alguns minutos."}), 429
    if not re.fullmatch(r"[0-9A-Z]{5,20}", ra):
        return jsonify({"ok": False, "erro": "RA inválido."}), 400

    con = None
    try:
        con = db()
        with con.cursor() as cur:
            cur.execute("SELECT ra, nome, curso_slug, semestre FROM alunos WHERE ra = %s AND ativo = 1", (ra,))
            aluno = cur.fetchone()
            if not aluno:
                return jsonify({"ok": False, "erro": "RA não cadastrado para este teste."}), 404

            cur.execute(
                "INSERT INTO dispositivos (mac_hash) VALUES (%s) "
                "ON DUPLICATE KEY UPDATE ultimo_acesso = CURRENT_TIMESTAMP", (hash_mac(ident),))
            cur.execute(
                "INSERT INTO sessoes_aluno (dispositivo_id, ra) "
                "SELECT id, %s FROM dispositivos WHERE mac_hash = %s", (ra, hash_mac(ident)))

            cur.execute(
                "SELECT titulo, mensagem FROM avisos WHERE ativo = 1 AND publico = 'alunos' "
                "AND (curso_slug IS NULL OR curso_slug = %s) "
                "AND (inicio IS NULL OR inicio <= NOW()) AND (fim IS NULL OR fim >= NOW()) "
                "ORDER BY id DESC LIMIT 10", (aluno["curso_slug"],))
            avisos = cur.fetchall()

            cur.execute(
                "SELECT dia_semana, hora_inicio, hora_fim, disciplina, sala FROM horarios_aula "
                "WHERE curso_slug = %s AND semestre = %s ORDER BY dia_semana, hora_inicio",
                (aluno["curso_slug"], aluno["semestre"]))
            horarios = [{
                "dia": r["dia_semana"], "inicio": fmt_hora(r["hora_inicio"]),
                "fim": fmt_hora(r["hora_fim"]), "disciplina": r["disciplina"], "sala": r["sala"],
            } for r in cur.fetchall()]
    except Exception as erro:
        print(f"[banco] login: {erro}")
        return jsonify({"ok": False, "erro": "Serviço indisponível no momento."}), 503
    finally:
        if con:
            con.close()

    registrar_evento(ident, "login_aluno")
    return jsonify({"ok": True, "nome": aluno["nome"], "avisos": avisos, "horarios": horarios})


@app.route("/api/liberar", methods=["POST"])
def api_liberar():
    ip, mac = cliente()
    if not mac:
        print(f"[erro] sem MAC para {ip} (fora do hotspot ou ainda sem entrada ARP)")
        return jsonify({"ok": False, "erro": "Não consegui identificar o aparelho. Reconecte ao Wi-Fi."}), 400
    try:
        liberar_mac(mac, ip)
    except subprocess.CalledProcessError as erro:
        print(f"[erro] iptables ao liberar {mac}: {erro.stderr}")
        return jsonify({"ok": False, "erro": "Falha ao liberar acesso."}), 500
    registrar_evento(mac, "liberou")
    print(f"[liberado] {mac} ({ip}) por {SESSAO_MINUTOS} min")
    return jsonify({"ok": True, "minutos": SESSAO_MINUTOS})


# ----------------------------------------------------------------------
# RELATÓRIOS (só de fora do hotspot + token)
# ----------------------------------------------------------------------
def admin_autorizado():
    try:
        if ipaddress.ip_address(request.remote_addr) in REDE_HOTSPOT:
            return False
    except ValueError:
        return False
    token = request.args.get("token", "")
    return bool(ADMIN_TOKEN) and hmac.compare_digest(token, ADMIN_TOKEN)


def consultar(sql, params=()):
    con = db()
    try:
        with con.cursor() as cur:
            cur.execute(sql, params)
            return cur.fetchall()
    finally:
        con.close()


SQL_CURSOS = """
SELECT c.nome,
       COALESCE(SUM(e.tipo = 'ver_curso'), 0)                                   AS visualizacoes,
       COUNT(DISTINCT CASE WHEN e.tipo = 'ver_curso' THEN e.dispositivo_id END) AS visitantes_unicos,
       COUNT(DISTINCT CASE WHEN e.tipo = 'interesse' THEN e.dispositivo_id END) AS interessados
FROM cursos c LEFT JOIN eventos e ON e.curso_slug = c.slug
GROUP BY c.slug, c.nome
ORDER BY visualizacoes DESC, c.nome
"""

SQL_HORAS = """
SELECT DATE_FORMAT(criado_em, '%Y-%m-%d %H:00') AS hora, COUNT(*) AS visualizacoes
FROM eventos WHERE tipo = 'ver_curso' GROUP BY hora ORDER BY hora
"""

SQL_TOTAIS = """
SELECT (SELECT COUNT(*) FROM dispositivos)                                      AS aparelhos,
       (SELECT COUNT(DISTINCT dispositivo_id) FROM eventos WHERE tipo = 'liberou')     AS liberaram,
       (SELECT COUNT(DISTINCT dispositivo_id) FROM eventos WHERE tipo = 'interesse')   AS declararam_interesse,
       (SELECT COUNT(DISTINCT dispositivo_id) FROM sessoes_aluno)                      AS alunos_logados
"""


def tabela_html(titulo, linhas, colunas):
    cab = "".join(f"<th>{html.escape(c)}</th>" for c in colunas.values())
    corpo = "".join(
        "<tr>" + "".join(f"<td>{html.escape(str(l[k]))}</td>" for k in colunas) + "</tr>"
        for l in linhas)
    return f"<h2>{html.escape(titulo)}</h2><table><tr>{cab}</tr>{corpo}</table>"


@app.route("/admin/relatorio")
def admin_relatorio():
    if not admin_autorizado():
        return Response("Acesso negado.", status=403)
    try:
        totais = consultar(SQL_TOTAIS)[0]
        cursos = consultar(SQL_CURSOS)
        horas = consultar(SQL_HORAS)
    except Exception as erro:
        return Response(f"Erro no banco: {html.escape(str(erro))}", status=500)

    t = tabela_html("Totais", [totais], {
        "aparelhos": "Aparelhos (únicos)", "liberaram": "Clicaram em liberar",
        "declararam_interesse": "Declararam interesse", "alunos_logados": "Alunos logados (RA)"})
    c = tabela_html("Interesse por curso", cursos, {
        "nome": "Curso", "visualizacoes": "Visualizações",
        "visitantes_unicos": "Visitantes únicos", "interessados": "Clicaram em 'Tenho interesse'"})
    h = tabela_html("Visualizações por hora", horas, {"hora": "Hora", "visualizacoes": "Visualizações"})
    pagina = f"""<!DOCTYPE html><html lang="pt-BR"><head><meta charset="utf-8">
<title>Relatório do portal</title>
<style>body{{font-family:sans-serif;max-width:900px;margin:24px auto;padding:0 16px}}
table{{border-collapse:collapse;width:100%;margin-bottom:24px}}
td,th{{border:1px solid #ccc;padding:6px 10px;text-align:left}}th{{background:#f3f3f3}}</style></head>
<body><h1>Portal Fatec Jahu — relatório</h1>
<p>Gerado em {datetime.now():%d/%m/%Y %H:%M}.
<a href="/admin/eventos.csv?token={html.escape(request.args.get('token', ''))}">Baixar eventos (CSV)</a></p>
{t}{c}{h}</body></html>"""
    return Response(pagina, mimetype="text/html")


@app.route("/admin/eventos.csv")
def admin_eventos_csv():
    if not admin_autorizado():
        return Response("Acesso negado.", status=403)
    try:
        linhas = consultar(
            "SELECT e.id, e.criado_em, LEFT(d.mac_hash, 10) AS aparelho, e.tipo, e.curso_slug "
            "FROM eventos e JOIN dispositivos d ON d.id = e.dispositivo_id ORDER BY e.id")
    except Exception as erro:
        return Response(f"Erro no banco: {erro}", status=500)
    saida = io.StringIO()
    escritor = csv.writer(saida)
    escritor.writerow(["id", "criado_em", "aparelho", "tipo", "curso"])
    for l in linhas:
        escritor.writerow([l["id"], l["criado_em"], l["aparelho"], l["tipo"], l["curso_slug"] or ""])
    return Response(saida.getvalue(), mimetype="text/csv",
                    headers={"Content-Disposition": "attachment; filename=eventos.csv"})


# ----------------------------------------------------------------------
# QUALQUER OUTRO ENDEREÇO -> PORTAL
# (sem isso o celular recebe "404" nas verificações e acha que é só "sem internet",
#  em vez de abrir a janela do portal)
# ----------------------------------------------------------------------
@app.route("/<path:caminho>", methods=["GET", "HEAD"])
def tudo_para_o_portal(caminho):
    return redirecionar_para_portal()


# ----------------------------------------------------------------------
if __name__ == "__main__":
    for nome, valor in (("SALT", SALT), ("ADMIN_TOKEN", ADMIN_TOKEN), ("DB_PASS", DB_PASS)):
        if not valor or valor.startswith("TROQUE"):
            print(f"[AVISO] {nome} ainda está com o valor padrão em config.env — troque antes do evento.")
    preparar_firewall()
    threading.Thread(target=limpar_expirados, daemon=True).start()
    # 0.0.0.0: escuta no hotspot (visitantes) e no cabo (você, para os relatórios)
    app.run(host="0.0.0.0", port=80, debug=False, threaded=True)

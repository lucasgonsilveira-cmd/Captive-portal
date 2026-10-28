# Portal cativo Fatec Jahu — kit para o TV box (MXQ Pro RK3228A)

Hotspot "TCC-Fatec-Jahu" que mostra os cursos antes de liberar a internet, mede o
interesse por curso no MariaDB e, para alunos pré-cadastrados (RA), mostra avisos
e horários de aula.

```
 celular ──Wi-Fi (wlan0, AP)──► [ TV box: hostapd + dnsmasq + iptables + Flask + MariaDB ]
                                         │ eth0 / usb0 / wlan1 (2º adaptador)
                                         ▼
                                   internet (opcional!)
```

> **Importante:** o portal e a coleta de dados funcionam **sem internet**. A internet
> só é o "prêmio" depois do clique. Se o 4G falhar no evento, a pesquisa continua.

## Arquivos

| Arquivo | Para quê |
|---|---|
| `config.env` | **Único lugar para configurar** (interfaces, senha do banco, SALT, token) |
| `rede.sh` | Sobe/derruba hotspot na ordem certa: `sudo ./rede.sh start`, `stop` ou `status` |
| `hostapd.conf` / `dnsmasq.conf` / `firewall.sh` | Wi-Fi AP, DHCP+DNS e regras de bloqueio/liberação |
| `app.py` | Backend Flask (portal, liberação, RA, relatórios) |
| `portal-fatec-jahu.html` | A página (já integrada ao backend) |
| `schema.sql`, `criar_usuario.sql`, `cadastrar_alunos.sql` | Banco, usuário do app e cadastro de alunos (só ASCII, prontos para o Workbench) |
| `systemd/` | Para tudo subir sozinho quando ligar o box |

---

## Etapa 1 — Linux no TV box (sem apagar o Android no começo)

Use o **Armbian para RK322x** (fórum: https://forum.armbian.com/topic/34923-csc-armbian-for-rk322x-tv-box-boards/ — o primeiro post tem imagens e instruções atualizadas).

1. Baixe o **Multitool** e a imagem Armbian (Debian, versão *minimal/CLI*) do primeiro post do fórum.
2. Grave o Multitool num cartão microSD (balenaEtcher), copie a imagem do Armbian para a pasta `images` do cartão.
3. Com o box desligado, coloque o cartão e ligue. O Multitool mostra **que tipo de memória o box tem (eMMC ou NAND)**. Anote.
4. **Faça backup da memória interna** pelo próprio Multitool antes de qualquer outra coisa.
5. Teste sempre **bootando pelo cartão antes de gravar na memória interna**. Siga as instruções do primeiro post do fórum para o seu tipo de memória (eMMC e NAND têm caminhos diferentes — o Armbian *mainline* não acessa NAND).
6. No primeiro boot (demora alguns minutos), defina as senhas e rode `sudo rk322x-config` para habilitar o chip Wi-Fi.

## Etapa 2 — DECISÃO: o Wi-Fi do box serve como hotspot?

Esta é a etapa que decide tudo. Com o box ligado no cabo (SSH):

```bash
ip -br link                         # deve aparecer wlan0
iw list | grep -A12 "Supported interface modes"
```

* Aparece `* AP` na lista → **ótimo**, o Wi-Fi interno vira hotspot. Siga para a Etapa 3.
* **Não** aparece `AP`, ou não existe wlan0 → o chip interno não faz hotspot. Use um **adaptador Wi-Fi USB** (plano B) e mande o resultado de `lsusb` para identificarmos o chip/driver. Troque `wlan0` pelo nome da interface do adaptador em `config.env`, `hostapd.conf` e `dnsmasq.conf`.

> Por que o notebook não deu certo: um único rádio Wi-Fi não consegue ser hotspot **e** receber internet por Wi-Fi ao mesmo tempo. O hotspot usa 1 interface; a internet precisa chegar por **outra** (cabo, USB do celular ou 2º adaptador). O TV box tem porta de rede e portas USB, então isso se resolve.

## Etapa 3 — Instalar os pacotes

```bash
sudo apt update
sudo apt install -y hostapd dnsmasq iptables iproute2 iw rfkill conntrack \
                    python3-flask python3-pymysql mariadb-server
sudo systemctl disable --now dnsmasq             # o rede.sh inicia o dnsmasq e o hostapd por conta própria
# (se o systemd avisar que o hostapd está "masked", ignore: é o normal no Debian)
sudo timedatectl set-timezone America/Sao_Paulo
```

## Etapa 4 — Banco de dados (Workbench ou terminal)

Os três arquivos `.sql` são **só ASCII** (sem acentos) para abrir sem erro no MySQL Workbench.
Rode nesta ordem, com a conexão **root**:

1. `schema.sql` — cria o banco, as tabelas e os dados de exemplo (pode rodar mais de uma vez).
2. `criar_usuario.sql` — troque `SUA_SENHA` (a mesma de `DB_PASS` no `config.env`) e execute.
3. `cadastrar_alunos.sql` — modelo para cadastrar seus alunos, horários e avisos.

**No Workbench:** *File > Open SQL Script...* > escolha o arquivo > clique no raio (Execute).
**No terminal:** `sudo mariadb < schema.sql` (e o mesmo para os outros).

Dica do Workbench: ele vem com "Safe Updates" ligado e só deixa `UPDATE`/`DELETE` usando a chave
(`WHERE id = 1`, `WHERE ra = '...'`). Confira o id com `SELECT id, titulo FROM avisos;`.
Os nomes dos cursos no banco ficam sem acento (`Construcao Naval`); isso só afeta o relatório,
a página do portal continua com acentos.

(`curso_slug`: cn, dsm, gpi, gti, ge, log, marh, si, sn, en, ep. Apague o aluno `00000TESTE` antes do evento.)

## Etapa 5 — Configurar e subir

```bash
sudo mkdir -p /opt/portal && sudo cp -r ./* /opt/portal/ && cd /opt/portal
sudo nano config.env        # troque DB_PASS, SALT e ADMIN_TOKEN (openssl rand -hex 16)
sudo ./rede.sh start        # hotspot + firewall
sudo python3 app.py         # portal (deixe rodando; Ctrl+C para parar)
```

Em outro terminal: `sudo ./rede.sh status`.

**Para subir sozinho ao ligar o box:**

```bash
sudo cp systemd/*.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now portal-rede portal-app
```

## Etapa 6 — Testes (nesta ordem, com o celular)

1. A rede **TCC-Fatec-Jahu** aparece e o celular conecta? (se não: `sudo hostapd -d /opt/portal/hostapd.conf`)
2. O celular recebe IP 192.168.50.x? (`cat /run/portal/dnsmasq.leases`)
3. A janela do portal **abre sozinha**? (Se não, abra `http://192.168.50.1` no navegador.)
4. Abra um curso → clique **Tenho interesse** → volte → `sudo mariadb portal_fatec -e "SELECT * FROM eventos"`.
5. Entre com um RA cadastrado → aparecem avisos e horário?
6. Clique **Liberar acesso** → o Google abre? (Precisa de internet no `UP_IF`.)
7. Com o cabo desconectado: o portal ainda abre e conta eventos? (deve — é o plano B do evento)
8. Relatório, **do seu notebook ligado no cabo do box** (não pelo Wi-Fi do hotspot):
   `http://IP_DO_BOX/admin/relatorio?token=SEU_TOKEN` — ou no próprio box:
   `curl "http://localhost/admin/relatorio?token=SEU_TOKEN"`.
   O CSV bruto para análise: `/admin/eventos.csv?token=...`

## Internet (uplink) no dia do evento — escolha UMA e teste antes

| Opção | Como | Observação |
|---|---|---|
| Cabo | Box ↔ roteador 4G / rede da faculdade em `eth0` | Mais simples e estável. É o que você usa nos testes. |
| USB do celular | Cabo USB no box + "Tethering USB" no Android → aparece `usb0`/`enx...` (`ip -br link`) | Ponha o nome em `UP_IF`. Teste antes. |
| 2º Wi-Fi USB | Adaptador conectado ao hotspot do celular | Precisa de driver; exige mais configuração. |

Se mudar `UP_IF` com o hotspot rodando: edite `config.env` e rode `sudo ./rede.sh start` de novo (os visitantes liberados precisam clicar outra vez).

## Checklist do dia do evento

- [ ] **Relógio do box:** o TV box **não tem bateria de relógio**: ao ligar sem internet, a hora volta para uma data antiga e todos os horários do relatório ficam errados. Acerte antes: `sudo timedatectl set-ntp false; sudo timedatectl set-time "2026-MM-DD HH:MM:00"`, e confira com `date`.
- [ ] Trocar o canal Wi-Fi se o local estiver cheio (`hostapd.conf`).
- [ ] `sudo ./rede.sh status` — hostapd e dnsmasq rodando.
- [ ] Teste com 2 celulares diferentes (Android e iPhone).
- [ ] Fonte de energia do box boa (5V/2A) e cartão SD de qualidade.
- [ ] Ao final: `mysqldump portal_fatec > backup.sql` e baixe o `eventos.csv`. Se o banco falhar durante o evento, os eventos ficam em `eventos_pendentes.jsonl` na pasta do app.

## Privacidade (importante para a pesquisa)

* O banco **não guarda o MAC real**, só um hash com segredo (SALT). Conta visitantes únicos sem identificar ninguém.
* No evento, visitantes (alunos do ensino médio, alguns menores de idade) **não se cadastram**: só geram cliques anônimos. Cadastro por RA é só para o grupo de alunos do teste.
* O RA sozinho é um identificador fraco (não é senha). Serve para este teste de baixo risco (ver avisos de aula). Combine com seu orientador se o TCC precisa de termo de consentimento (TCLE) para o grupo de alunos.
* O hotspot é aberto e os visitantes ficam isolados uns dos outros (`ap_isolate`).

## Problemas comuns

| Sintoma | Causa provável | O que fazer |
|---|---|---|
| `rfkill: WLAN soft blocked` | Wi-Fi bloqueado por software | `sudo rfkill unblock wifi` (o rede.sh já faz) |
| hostapd: "Could not connect to kernel driver" / falha ao subir | NetworkManager controlando a interface, ou chip sem modo AP | `nmcli device set wlan0 managed no`; confira `iw list` |
| Celular conecta mas diz "sem internet" e não abre o portal | dnsmasq ou app.py parados | `sudo ./rede.sh status`; `sudo ss -ltnp \| grep :80` |
| dnsmasq não sobe | Porta 53 ocupada | `sudo ss -lunp \| grep :53`; `sudo systemctl stop systemd-resolved` se for ele |
| Clica em liberar, mas não navega | Sem internet em `UP_IF` ou interface errada | `ip -br addr`; teste `ping -I eth0 8.8.8.8` no box |
| "Não consegui identificar o aparelho" | Aparelho sem entrada ARP | Reconectar ao Wi-Fi e tentar de novo |
| Banco sem dados | Senha errada no `config.env` | veja o log do `app.py` (`[banco] ...`) |

-- ============================================================================
-- SCHEMA.SQL - banco do portal cativo (MariaDB)
-- ============================================================================
-- Arquivo 100% ASCII (sem acentos): abre e salva sem erro no MySQL Workbench.
--
-- COMO CARREGAR
--   Workbench: File > Open SQL Script... > escolha este arquivo > clique no raio
--              (Execute) com a conexao root. Pode rodar mais de uma vez sem problema.
--   Terminal:  sudo mariadb < schema.sql
--
-- O QUE O BANCO GUARDA (e o que NAO guarda)
--   * NUNCA guarda o MAC real: so um hash (HMAC com o SALT do config.env).
--     Serve para contar "visitantes unicos" sem identificar ninguem.
--   * Visitante comum (Portas Abertas) nao se cadastra: so gera eventos anonimos.
--   * So quem esta na tabela `alunos` (cadastrada por voce, previamente) pode
--     entrar com RA e ver avisos/horarios.
-- ============================================================================

CREATE DATABASE IF NOT EXISTS portal_fatec
  CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
USE portal_fatec;

-- Cursos (os "slug" sao os mesmos ids usados no portal-fatec-jahu.html)
CREATE TABLE IF NOT EXISTS cursos (
  slug VARCHAR(10)  NOT NULL PRIMARY KEY,
  nome VARCHAR(100) NOT NULL
) ENGINE=InnoDB;

-- Se o script rodar de novo, apenas atualiza os nomes.
INSERT INTO cursos (slug, nome) VALUES
  ('cn',   'Construcao Naval'),
  ('dsm',  'Desenvolvimento de Software Multiplataforma'),
  ('gpi',  'Gestao da Producao Industrial'),
  ('gti',  'Gestao da Tecnologia da Informacao'),
  ('ge',   'Gestao Empresarial (EAD)'),
  ('log',  'Logistica'),
  ('marh', 'Meio Ambiente e Recursos Hidricos'),
  ('si',   'Sistemas para Internet'),
  ('sn',   'Sistemas de Navegacao Fluvial'),
  ('en',   'Engenharia Naval'),
  ('ep',   'Engenharia de Producao')
ON DUPLICATE KEY UPDATE nome = VALUES(nome);

-- Aparelhos (anonimos)
CREATE TABLE IF NOT EXISTS dispositivos (
  id              INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  mac_hash        CHAR(64)     NOT NULL UNIQUE,
  primeiro_acesso TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP,
  ultimo_acesso   TIMESTAMP    NOT NULL DEFAULT CURRENT_TIMESTAMP
) ENGINE=InnoDB;

-- Tudo o que o visitante faz no portal
--   abertura    = abriu o portal
--   ver_curso   = abriu a pagina de um curso   (INTERESSE PASSIVO)
--   interesse   = clicou em "Tenho interesse"  (INTERESSE DECLARADO)
--   login_aluno = entrou com RA
--   liberou     = clicou em "Liberar acesso"
CREATE TABLE IF NOT EXISTS eventos (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  dispositivo_id INT UNSIGNED    NOT NULL,
  tipo           ENUM('abertura','ver_curso','interesse','login_aluno','liberou') NOT NULL,
  curso_slug     VARCHAR(10)     NULL,
  criado_em      TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  INDEX idx_tipo_curso (tipo, curso_slug),
  INDEX idx_criado (criado_em),
  CONSTRAINT fk_ev_disp  FOREIGN KEY (dispositivo_id) REFERENCES dispositivos(id),
  CONSTRAINT fk_ev_curso FOREIGN KEY (curso_slug)     REFERENCES cursos(slug)
) ENGINE=InnoDB;

-- Lista de alunos autorizados no teste (cadastro feito por VOCE, nao pelo visitante)
CREATE TABLE IF NOT EXISTS alunos (
  ra         VARCHAR(20)  NOT NULL PRIMARY KEY,
  nome       VARCHAR(100) NULL,
  curso_slug VARCHAR(10)  NOT NULL,
  semestre   TINYINT UNSIGNED NOT NULL,
  ativo      TINYINT(1)   NOT NULL DEFAULT 1,
  CONSTRAINT fk_al_curso FOREIGN KEY (curso_slug) REFERENCES cursos(slug)
) ENGINE=InnoDB;

-- Quem (RA) entrou em qual aparelho, e quando
CREATE TABLE IF NOT EXISTS sessoes_aluno (
  id             BIGINT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  dispositivo_id INT UNSIGNED    NOT NULL,
  ra             VARCHAR(20)     NOT NULL,
  login_em       TIMESTAMP       NOT NULL DEFAULT CURRENT_TIMESTAMP,
  CONSTRAINT fk_se_disp FOREIGN KEY (dispositivo_id) REFERENCES dispositivos(id),
  CONSTRAINT fk_se_ra   FOREIGN KEY (ra)             REFERENCES alunos(ra)
) ENGINE=InnoDB;

-- Avisos: publico = 'todos' aparece para qualquer visitante (ex.: vestibular);
--         publico = 'alunos' so depois do login com RA.
CREATE TABLE IF NOT EXISTS avisos (
  id         INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  titulo     VARCHAR(120) NOT NULL,
  mensagem   TEXT         NOT NULL,
  publico    ENUM('todos','alunos') NOT NULL DEFAULT 'todos',
  curso_slug VARCHAR(10)  NULL,
  inicio     DATETIME     NULL,
  fim        DATETIME     NULL,
  ativo      TINYINT(1)   NOT NULL DEFAULT 1,
  CONSTRAINT fk_av_curso FOREIGN KEY (curso_slug) REFERENCES cursos(slug)
) ENGINE=InnoDB;

-- Horarios de aula (dia_semana: 1 = segunda ... 6 = sabado)
CREATE TABLE IF NOT EXISTS horarios_aula (
  id          INT UNSIGNED NOT NULL AUTO_INCREMENT PRIMARY KEY,
  curso_slug  VARCHAR(10)  NOT NULL,
  semestre    TINYINT UNSIGNED NOT NULL,
  dia_semana  TINYINT UNSIGNED NOT NULL,
  hora_inicio TIME         NOT NULL,
  hora_fim    TIME         NOT NULL,
  disciplina  VARCHAR(100) NOT NULL,
  sala        VARCHAR(30)  NULL,
  CONSTRAINT fk_ho_curso FOREIGN KEY (curso_slug) REFERENCES cursos(slug)
) ENGINE=InnoDB;

-- ----------------------------------------------------------------------------
-- DADOS DE EXEMPLO - troque pelos reais (use o arquivo cadastrar_alunos.sql)
-- ----------------------------------------------------------------------------

-- Aviso para QUALQUER visitante (edite o texto depois com o edital oficial)
INSERT INTO avisos (titulo, mensagem, publico)
SELECT 'Vestibular Fatec', 'EDITE AQUI: datas de inscricao e prova conforme o edital oficial.', 'todos'
FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM avisos WHERE titulo = 'Vestibular Fatec');

-- Aluno de teste (RA FICTICIO), horario e aviso de exemplo
INSERT IGNORE INTO alunos (ra, nome, curso_slug, semestre)
VALUES ('00000TESTE', 'Aluno Teste', 'gti', 5);

INSERT INTO horarios_aula (curso_slug, semestre, dia_semana, hora_inicio, hora_fim, disciplina, sala)
SELECT 'gti', 5, 1, '19:00', '20:40', 'EXEMPLO - Disciplina A', 'Sala 1'
FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM horarios_aula WHERE disciplina = 'EXEMPLO - Disciplina A');

INSERT INTO avisos (titulo, mensagem, publico, curso_slug)
SELECT 'Aviso de aula (exemplo)', 'EXEMPLO: aula de segunda-feira passou para a sala 2.', 'alunos', 'gti'
FROM DUAL
WHERE NOT EXISTS (SELECT 1 FROM avisos WHERE titulo = 'Aviso de aula (exemplo)');

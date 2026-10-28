-- ============================================================================
-- CRIAR_USUARIO.SQL - usuario do banco que o app.py usa (rode DEPOIS do schema.sql)
-- ============================================================================
-- 1) Troque SUA_SENHA pela MESMA senha que voce colocar em DB_PASS no config.env.
-- 2) Workbench: File > Open SQL Script... > execute (raio) com a conexao root.
--    Terminal:  sudo mariadb < criar_usuario.sql
--
-- Sao criados dois usuarios (localhost e 127.0.0.1) porque, dependendo da
-- configuracao do MariaDB, a conexao do app.py chega por um ou pelo outro.
-- O usuario so pode ler, inserir e atualizar (nao apaga nem altera tabelas).
-- ============================================================================

CREATE USER IF NOT EXISTS 'portal'@'localhost'  IDENTIFIED BY 'SUA_SENHA';
CREATE USER IF NOT EXISTS 'portal'@'127.0.0.1'  IDENTIFIED BY 'SUA_SENHA';

GRANT SELECT, INSERT, UPDATE ON portal_fatec.* TO 'portal'@'localhost';
GRANT SELECT, INSERT, UPDATE ON portal_fatec.* TO 'portal'@'127.0.0.1';

FLUSH PRIVILEGES;

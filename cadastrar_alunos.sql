-- ============================================================================
-- CADASTRAR_ALUNOS.SQL - modelo para cadastrar alunos, horarios e avisos
-- ============================================================================
-- Copie/edite as linhas abaixo e execute no Workbench (raio) ou no terminal:
--   sudo mariadb < cadastrar_alunos.sql
-- curso_slug: cn, dsm, gpi, gti, ge, log, marh, si, sn, en, ep
-- dia_semana: 1 = segunda ... 6 = sabado
-- ============================================================================
USE portal_fatec;

-- Alunos do teste (so quem esta aqui consegue entrar com RA)
INSERT INTO alunos (ra, nome, curso_slug, semestre) VALUES
  ('COLOQUE_O_RA_1', 'Nome do aluno 1', 'gti', 5),
  ('COLOQUE_O_RA_2', 'Nome do aluno 2', 'gti', 5);

-- Horarios de aula do curso/semestre
INSERT INTO horarios_aula (curso_slug, semestre, dia_semana, hora_inicio, hora_fim, disciplina, sala) VALUES
  ('gti', 5, 1, '19:00', '20:40', 'Nome da disciplina', 'Sala 3'),
  ('gti', 5, 3, '19:00', '22:30', 'Outra disciplina',   'Lab 2');

-- Aviso so para alunos (aparece depois do login com RA)
INSERT INTO avisos (titulo, mensagem, publico, curso_slug)
VALUES ('Aviso da semana', 'Escreva aqui o aviso.', 'alunos', 'gti');

-- ----------------------------------------------------------------------------
-- Editar o aviso do vestibular (aparece para TODOS os visitantes)
-- O Workbench, por padrao, so deixa fazer UPDATE/DELETE usando a chave (id).
-- Confira o id com:  SELECT id, titulo FROM avisos;
-- ----------------------------------------------------------------------------
-- UPDATE avisos SET mensagem = 'Texto oficial do vestibular' WHERE id = 1;

-- Remover o aluno de teste antes do evento (tambem pela chave):
-- DELETE FROM alunos WHERE ra = '00000TESTE';

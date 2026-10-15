"""agenda e conversas

Revision ID: e1add86284d5
Revises: 
Create Date: 2026-10-15 11:06:16.785828

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'e1add86284d5'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Upgrade schema."""
    # "=" on an integer inside a GiST exclusion constraint needs btree_gist.
    op.execute("CREATE EXTENSION IF NOT EXISTS btree_gist")
    op.create_table('barbeiros',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('nome', sa.String(length=80), nullable=False),
    sa.Column('ativo', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_barbeiros')),
    sa.UniqueConstraint('nome', name=op.f('uq_barbeiros_nome'))
    )
    op.create_table('conversas',
    sa.Column('id', sa.Uuid(), nullable=False),
    sa.Column('canal', sa.Enum('voz', 'texto', 'eval', name='canal'), nullable=False),
    sa.Column('modelo', sa.String(length=80), nullable=True),
    sa.Column('iniciada_em', sa.DateTime(timezone=True), nullable=False),
    sa.Column('encerrada_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('duracao_s', sa.Integer(), nullable=True),
    sa.Column('tokens_entrada', sa.Integer(), nullable=False),
    sa.Column('tokens_saida', sa.Integer(), nullable=False),
    sa.Column('custo_usd', sa.Numeric(precision=10, scale=6), nullable=False),
    sa.Column('latencia_media_ms', sa.Integer(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_conversas'))
    )
    op.create_table('servicos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('nome', sa.String(length=80), nullable=False),
    sa.Column('duracao_min', sa.SmallInteger(), nullable=False),
    sa.Column('preco_centavos', sa.Integer(), nullable=False),
    sa.Column('ativo', sa.Boolean(), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_servicos')),
    sa.UniqueConstraint('nome', name=op.f('uq_servicos_nome'))
    )
    op.create_table('agendamentos',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('cliente_nome', sa.String(length=120), nullable=False),
    sa.Column('cliente_telefone', sa.String(length=11), nullable=False),
    sa.Column('servico_id', sa.Integer(), nullable=False),
    sa.Column('barbeiro_id', sa.Integer(), nullable=False),
    sa.Column('inicio', sa.DateTime(timezone=True), nullable=False),
    sa.Column('fim', sa.DateTime(timezone=True), nullable=False),
    sa.Column('periodo', postgresql.TSTZRANGE(), sa.Computed("tstzrange(inicio, fim, '[)')", persisted=True), nullable=False),
    sa.Column('status', sa.Enum('agendado', 'cancelado', name='statusagendamento'), nullable=False),
    sa.Column('cancelado_em', sa.DateTime(timezone=True), nullable=True),
    sa.Column('conversa_id', sa.Uuid(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    postgresql.ExcludeConstraint((sa.column('barbeiro_id'), '='), (sa.column('periodo'), '&&'), where=sa.text("status = 'agendado'"), using='gist', name='sem_conflito'),
    sa.ForeignKeyConstraint(['barbeiro_id'], ['barbeiros.id'], name=op.f('fk_agendamentos_barbeiro_id_barbeiros')),
    sa.ForeignKeyConstraint(['conversa_id'], ['conversas.id'], name=op.f('fk_agendamentos_conversa_id_conversas'), ondelete='SET NULL'),
    sa.ForeignKeyConstraint(['servico_id'], ['servicos.id'], name=op.f('fk_agendamentos_servico_id_servicos')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_agendamentos'))
    )
    op.create_index(op.f('ix_agendamentos_cliente_telefone'), 'agendamentos', ['cliente_telefone'], unique=False)
    op.create_index(op.f('ix_agendamentos_inicio'), 'agendamentos', ['inicio'], unique=False)
    op.create_table('expedientes',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('barbeiro_id', sa.Integer(), nullable=False),
    sa.Column('dia_semana', sa.SmallInteger(), nullable=False),
    sa.Column('inicio', sa.Time(), nullable=False),
    sa.Column('fim', sa.Time(), nullable=False),
    sa.ForeignKeyConstraint(['barbeiro_id'], ['barbeiros.id'], name=op.f('fk_expedientes_barbeiro_id_barbeiros'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_expedientes'))
    )
    op.create_table('mensagens',
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('conversa_id', sa.Uuid(), nullable=False),
    sa.Column('papel', sa.Enum('cliente', 'agente', 'ferramenta', name='papel'), nullable=False),
    sa.Column('conteudo', sa.Text(), nullable=False),
    sa.Column('ferramenta', sa.String(length=40), nullable=True),
    sa.Column('dados', postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    sa.Column('latencia_ms', sa.Integer(), nullable=True),
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
    sa.ForeignKeyConstraint(['conversa_id'], ['conversas.id'], name=op.f('fk_mensagens_conversa_id_conversas'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_mensagens'))
    )
    op.create_index(op.f('ix_mensagens_conversa_id'), 'mensagens', ['conversa_id'], unique=False)


def downgrade() -> None:
    """Downgrade schema."""
    op.drop_index(op.f('ix_mensagens_conversa_id'), table_name='mensagens')
    op.drop_table('mensagens')
    op.drop_table('expedientes')
    op.drop_index(op.f('ix_agendamentos_inicio'), table_name='agendamentos')
    op.drop_index(op.f('ix_agendamentos_cliente_telefone'), table_name='agendamentos')
    op.drop_table('agendamentos')
    op.drop_table('servicos')
    op.drop_table('conversas')
    sa.Enum(name='papel').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='canal').drop(op.get_bind(), checkfirst=True)
    sa.Enum(name='statusagendamento').drop(op.get_bind(), checkfirst=True)
    op.drop_table('barbeiros')

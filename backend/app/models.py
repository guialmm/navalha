import enum
import uuid
from datetime import datetime, time
from decimal import Decimal

from sqlalchemy import (
    Computed,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    String,
    Text,
    Time,
    text,
)
from sqlalchemy.dialects.postgresql import ExcludeConstraint, JSONB, TSTZRANGE
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.db import Base, TimestampMixin


def pg_enum(cls: type[enum.Enum]) -> Enum:
    return Enum(cls, name=cls.__name__.lower(), values_callable=lambda e: [m.value for m in e])


class Servico(Base):
    __tablename__ = "servicos"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(80), unique=True)
    duracao_min: Mapped[int] = mapped_column(SmallInteger)
    preco_centavos: Mapped[int] = mapped_column(Integer)
    ativo: Mapped[bool] = mapped_column(default=True)


class Barbeiro(Base):
    __tablename__ = "barbeiros"

    id: Mapped[int] = mapped_column(primary_key=True)
    nome: Mapped[str] = mapped_column(String(80), unique=True)
    ativo: Mapped[bool] = mapped_column(default=True)

    expedientes: Mapped[list["Expediente"]] = relationship(
        back_populates="barbeiro", cascade="all, delete-orphan"
    )


class Expediente(Base):
    """A working window. Two rows on the same weekday make a lunch break."""

    __tablename__ = "expedientes"

    id: Mapped[int] = mapped_column(primary_key=True)
    barbeiro_id: Mapped[int] = mapped_column(ForeignKey("barbeiros.id", ondelete="CASCADE"))
    dia_semana: Mapped[int] = mapped_column(SmallInteger)  # 0 = Monday, like date.weekday()
    inicio: Mapped[time] = mapped_column(Time)
    fim: Mapped[time] = mapped_column(Time)

    barbeiro: Mapped[Barbeiro] = relationship(back_populates="expedientes")


class StatusAgendamento(str, enum.Enum):
    agendado = "agendado"
    cancelado = "cancelado"


class Agendamento(TimestampMixin, Base):
    __tablename__ = "agendamentos"
    __table_args__ = (
        # The database, not the prompt, guarantees a barber is never double-booked:
        # two active appointments for the same barber cannot overlap, even if two
        # calls try to grab the last slot in the same millisecond.
        ExcludeConstraint(
            ("barbeiro_id", "="),
            ("periodo", "&&"),
            name="sem_conflito",
            using="gist",
            where=text("status = 'agendado'"),
        ),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    cliente_nome: Mapped[str] = mapped_column(String(120))
    cliente_telefone: Mapped[str] = mapped_column(String(11), index=True)  # digits only
    servico_id: Mapped[int] = mapped_column(ForeignKey("servicos.id"))
    barbeiro_id: Mapped[int] = mapped_column(ForeignKey("barbeiros.id"))
    inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    fim: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    periodo: Mapped[object] = mapped_column(
        TSTZRANGE, Computed("tstzrange(inicio, fim, '[)')", persisted=True)
    )
    status: Mapped[StatusAgendamento] = mapped_column(
        pg_enum(StatusAgendamento), default=StatusAgendamento.agendado
    )
    cancelado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    conversa_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("conversas.id", ondelete="SET NULL")
    )

    servico: Mapped[Servico] = relationship(lazy="joined")
    barbeiro: Mapped[Barbeiro] = relationship(lazy="joined")


class Canal(str, enum.Enum):
    voz = "voz"
    texto = "texto"
    eval = "eval"


class Conversa(Base):
    """One call: transcript, duration and what it would cost on a paid plan."""

    __tablename__ = "conversas"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
    canal: Mapped[Canal] = mapped_column(pg_enum(Canal))
    modelo: Mapped[str | None] = mapped_column(String(80))
    iniciada_em: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    encerrada_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    duracao_s: Mapped[int | None] = mapped_column(Integer)
    tokens_entrada: Mapped[int] = mapped_column(Integer, default=0)
    tokens_saida: Mapped[int] = mapped_column(Integer, default=0)
    custo_usd: Mapped[Decimal] = mapped_column(Numeric(10, 6), default=0)
    latencia_media_ms: Mapped[int | None] = mapped_column(Integer)

    mensagens: Mapped[list["Mensagem"]] = relationship(
        back_populates="conversa", order_by="Mensagem.id", cascade="all, delete-orphan"
    )


class Papel(str, enum.Enum):
    cliente = "cliente"
    agente = "agente"
    ferramenta = "ferramenta"


class Mensagem(TimestampMixin, Base):
    __tablename__ = "mensagens"

    id: Mapped[int] = mapped_column(primary_key=True)
    conversa_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversas.id", ondelete="CASCADE"), index=True
    )
    papel: Mapped[Papel] = mapped_column(pg_enum(Papel))
    conteudo: Mapped[str] = mapped_column(Text)
    # Tool calls: name, arguments and result, so a bad booking can be traced back.
    ferramenta: Mapped[str | None] = mapped_column(String(40))
    dados: Mapped[dict | None] = mapped_column(JSONB)
    # Agent turns: end of the customer's speech → first audio out.
    latencia_ms: Mapped[int | None] = mapped_column(Integer)

    conversa: Mapped[Conversa] = relationship(back_populates="mensagens")

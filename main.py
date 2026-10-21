"""Verifica alterações de preço de venda no Sankhya e avisa por e-mail.

Uso:
    python main.py                   # um ciclo (para usar com cron a cada 10 min)
    python main.py --loop            # fica rodando, um ciclo a cada INTERVALO_MINUTOS
    python main.py --carga-completa  # recalcula todos os preços vigentes e compara com o banco
    python main.py --testar-email    # envia um e-mail de teste aos destinatários
    python main.py --testar-telegram # envia um aviso de teste no Telegram
"""

import argparse
import logging
import signal
import sys
import time
from dataclasses import dataclass
from datetime import datetime

from notifica_precos import config as cfg
from notifica_precos import envio_email, logs, mensagem, telegram
from notifica_precos.banco import Banco
from notifica_precos.sankhya import Sankhya
from notifica_precos.snapshot import (
    Chave, Diferenca, Preco, Snapshot, Versao, aplicar_versoes, comparar_completo, de_registro, versao_de_registro,
)

log = logging.getLogger("notifica_precos")

# Acima disso, as alterações não são logadas uma a uma (ficam na tabela historico e no CSV).
MAX_ALTERACOES_NO_LOG = 200

# Uma versão com pelo menos essa fração dos produtos ativos é tratada como cópia completa da tabela.
FRACAO_COPIA_COMPLETA = 0.1
# Quantas versões são contadas por consulta ao procurar a cópia completa mais recente.
LOTE_VERSOES = 20

PRIMEIRA_CARGA = "primeira carga"

_parar = False


@dataclass
class Resumo:
    """O que um ciclo fez; decide se vale um aviso no Telegram."""
    completa: bool
    detalhe: str  # motivo da carga completa ou versões aplicadas
    precos: int = 0
    alteracoes: int = 0
    email_enviado: bool = False

    @property
    def relevante(self) -> bool:
        return self.completa or self.alteracoes > 0


def motivo_carga_completa(config: cfg.Config, snapshot: Snapshot, forcar: bool) -> str | None:
    if forcar:
        return "solicitada (--carga-completa)"
    if snapshot.estado("carga_inicial_concluida") != "1":
        return PRIMEIRA_CARGA
    if config.render_git_commit and config.render_git_commit != snapshot.estado("ultimo_commit"):
        return f"novo deploy ({config.render_git_commit[:7]})"
    if config.carga_completa_hora is not None:
        # Uma vez por dia, na primeira execução a partir do horário fixo (fuso de TZ). Se um deploy
        # já fez uma carga completa depois desse horário hoje, não repete.
        agora = datetime.now()
        horario = agora.replace(hour=config.carga_completa_hora, minute=0, second=0, microsecond=0)
        ultima = snapshot.estado("ultima_carga_completa")
        if agora >= horario and (not ultima or datetime.fromisoformat(ultima) < horario):
            return f"reconciliação diária ({config.carga_completa_hora}h)"
    return None


def notificar(config: cfg.Config, dif: Diferenca, origem: str) -> bool:
    """Loga e envia o e-mail. Se o envio falhar, a exceção sobe e nada é gravado no banco,
    então as mesmas alterações são detectadas e reenviadas no próximo ciclo."""
    alteracoes = dif.alteracoes
    if len(alteracoes) <= MAX_ALTERACOES_NO_LOG:
        for a in alteracoes:
            log.info(
                "ALTERACAO tab=%s prod=%s local=%s controle=%r nutab=%s→%s valor=%s→%s %s",
                a.atual.codtab, a.atual.codprod, a.atual.codlocal, a.atual.controle,
                a.anterior.nutab if a.anterior else "-", a.atual.nutab,
                a.anterior.vlrvenda if a.anterior else "-", a.atual.vlrvenda, a.atual.descrprod,
            )
    else:
        log.info("%d alterações detectadas; detalhes na tabela historico e no CSV do e-mail", len(alteracoes))

    if not config.email_configurado:
        log.warning("E-mail não configurado: alterações registradas apenas no log")
        return False

    envio_email.enviar(
        config,
        mensagem.assunto(alteracoes),
        mensagem.texto(alteracoes, config.max_itens_email, origem),
        mensagem.html(alteracoes, config.max_itens_email, origem),
        anexos=[(f"alteracoes_precos_{time.strftime('%Y%m%d_%H%M')}.csv",
                 mensagem.csv_completo(alteracoes), "text/csv")],
    )
    return True


def precos_vigentes(config: cfg.Config, sankhya: Sankhya, versoes: list[Versao]) -> dict[Chave, Preco]:
    """Preço vigente de todos os produtos sem varrer o histórico da TGFEXC.

    A tabela é recriada a cada atualização, e a cópia completa mais recente já traz todos os
    produtos. Então basta partir dela e sobrepor as versões parciais que vieram depois.
    """
    limite = config.copia_completa_min_itens or max(1, int(sankhya.produtos_ativos() * FRACAO_COPIA_COMPLETA))
    atuais: dict[Chave, Preco] = {}
    for codtab in sorted({v.codtab for v in versoes}):
        da_tabela = sorted((v for v in versoes if v.codtab == codtab), key=lambda v: (v.dtvigor, v.nutab), reverse=True)

        base = None
        for i in range(0, len(da_tabela), LOTE_VERSOES):
            lote = da_tabela[i:i + LOTE_VERSOES]  # da mais nova para a mais antiga
            completas = sankhya.copias_completas([v.nutab for v in lote], limite)
            base = next((v for v in lote if v.nutab in completas), None)
            if base:
                break

        # Sem nenhuma cópia completa, todas as versões são parciais (pequenas) e são aplicadas.
        aplicar = da_tabela[:da_tabela.index(base) + 1] if base else da_tabela
        lidas = [(v, [de_registro(r) for r in sankhya.precos_versao(v.nutab)]) for v in aplicar]
        atuais.update({p.chave: p for p in aplicar_versoes({}, lidas).gravar})
        log.info(
            "Tabela %d: base %s + %d versão(ões) posterior(es) (cópia completa = %d+ itens)",
            codtab, f"NUTAB {base.nutab} de {base.dtvigor}" if base else "nenhuma cópia completa",
            len(aplicar) - (1 if base else 0), limite,
        )
    return atuais


def _duracao(segundos: float) -> str:
    minutos, seg = divmod(int(segundos), 60)
    horas, minutos = divmod(minutos, 60)
    return f"{horas}h{minutos:02d}m" if horas else f"{minutos}m{seg:02d}s"


def carga_inicial(config: cfg.Config, sankhya: Sankhya, snapshot: Snapshot) -> Resumo:
    """Primeira carga produto a produto (em lotes), para garantir que nenhum produto fique de fora.

    Cada lote é salvo junto com o último CODPROD concluído: se a execução cair no meio,
    a próxima continua dali em vez de recomeçar.
    """
    # Versões lidas antes dos preços: uma versão criada durante a carga não é marcada como
    # processada e é reaplicada no próximo ciclo (sem efeito se os preços já estiverem iguais).
    versoes = [versao_de_registro(r) for r in sankhya.versoes_tabela()]
    codigos = sankhya.codigos_produtos()
    checkpoint = snapshot.estado("carga_inicial_ate")
    # Sem checkpoint, processa todos (o Sankhya costuma ter um produto de código 0).
    ate = int(checkpoint) if checkpoint else None
    pendentes = codigos if ate is None else [c for c in codigos if c > ate]
    tamanho = config.carga_lote_produtos
    lotes = [pendentes[i:i + tamanho] for i in range(0, len(pendentes), tamanho)]
    feitos_antes = len(codigos) - len(pendentes)

    if ate is not None:
        log.info("Primeira carga: retomando após o produto %d (%d de %d já processados)", ate, feitos_antes, len(codigos))
    else:
        log.info("Primeira carga: %d produtos ativos em %d lote(s) de até %d", len(codigos), len(lotes), tamanho)

    inicio = time.monotonic()
    feitos = 0
    for n, lote in enumerate(lotes, 1):
        precos = {p.chave: p for p in map(de_registro, sankhya.precos_produtos(lote))}
        snapshot.salvar(Diferenca(gravar=list(precos.values())), notificado=False,
                        estado={"carga_inicial_ate": str(lote[-1])})
        feitos += len(lote)
        decorrido = time.monotonic() - inicio
        restante = decorrido / feitos * (len(pendentes) - feitos)
        log.info(
            "Primeira carga: lote %d/%d · produtos %d a %d · %d preço(s) · %d/%d produtos (%.1f%%) · %s decorridos · ~%s restantes",
            n, len(lotes), lote[0], lote[-1], len(precos), feitos_antes + feitos, len(codigos),
            (feitos_antes + feitos) / len(codigos) * 100, _duracao(decorrido), _duracao(restante),
        )

    estado = {"carga_inicial_concluida": "1", "ultima_carga_completa": datetime.now().isoformat(timespec="seconds")}
    if config.render_git_commit:
        estado["ultimo_commit"] = config.render_git_commit
    snapshot.salvar(Diferenca(), notificado=False, versoes=versoes, estado=estado)
    total = len(snapshot.precos())
    log.info("Primeira carga concluída em %s: %d preços de %d produtos; nada a notificar",
             _duracao(time.monotonic() - inicio), total, len(codigos))
    return Resumo(completa=True, detalhe=PRIMEIRA_CARGA, precos=total)


def carga_completa(config: cfg.Config, sankhya: Sankhya, snapshot: Snapshot, motivo: str) -> Resumo:
    log.info("Carga completa: %s", motivo)
    if motivo == PRIMEIRA_CARGA:
        return carga_inicial(config, sankhya, snapshot)
    # Versões lidas antes dos preços: uma versão criada entre as duas consultas não é marcada
    # como processada e é reaplicada no próximo ciclo (sem efeito se os preços forem iguais).
    versoes = [versao_de_registro(r) for r in sankhya.versoes_tabela()]
    atuais = precos_vigentes(config, sankhya, versoes)
    log.info("%d preços vigentes lidos do Sankhya (%d versões de tabela)", len(atuais), len(versoes))

    estado = {"ultima_carga_completa": datetime.now().isoformat(timespec="seconds")}
    if config.render_git_commit:
        estado["ultimo_commit"] = config.render_git_commit

    dif = comparar_completo(snapshot.precos(), atuais)
    if dif.removidos:
        # Não remove da foto: um produto ausente aqui (inativado ou fora da cópia completa usada
        # como base) voltaria depois como "novo" e geraria um aviso falso com o mesmo preço.
        log.info("%d item(ns) da foto não vieram nesta carga; mantidos no banco", len(dif.removidos))
        dif.removidos = []
    notificado = notificar(config, dif, f"carga completa: {motivo}") if dif.alteracoes else False
    snapshot.salvar(dif, notificado, versoes=versoes, estado=estado)
    log.info("Carga completa concluída: %d alteração(ões)", len(dif.alteracoes))
    return Resumo(True, motivo, len(atuais), len(dif.alteracoes), notificado)


def incremental(config: cfg.Config, sankhya: Sankhya, snapshot: Snapshot) -> Resumo:
    processadas = snapshot.versoes_processadas()
    novas = [v for v in map(versao_de_registro, sankhya.versoes_tabela()) if v.nutab not in processadas]
    if not novas:
        log.info("Nenhuma versão nova de tabela de preço")
        return Resumo(completa=False, detalhe="")

    lidas = []
    for v in sorted(novas, key=lambda v: (v.dtvigor, v.nutab)):
        precos = [de_registro(r) for r in sankhya.precos_versao(v.nutab)]
        log.info("Versão nova: NUTAB %d (tabela %d, vigor %s) com %d preço(s)", v.nutab, v.codtab, v.dtvigor, len(precos))
        lidas.append((v, precos))

    dif = aplicar_versoes(snapshot.precos(), lidas)
    notificado = notificar(config, dif, "nova versão da tabela") if dif.alteracoes else False
    snapshot.salvar(dif, notificado, versoes=novas)
    log.info("%d alteração(ões) de preço nas versões novas", len(dif.alteracoes))
    nutabs = ", ".join(str(v.nutab) for v, _ in lidas)
    return Resumo(False, f"NUTAB {nutabs}", sum(len(p) for _, p in lidas), len(dif.alteracoes), notificado)


def ciclo(config: cfg.Config, sankhya: Sankhya, snapshot: Snapshot, forcar_completa: bool = False) -> Resumo:
    inicio = time.monotonic()
    apagados = logs.limpar_antigos(snapshot.banco, config.log_dias_retencao)
    if apagados:
        log.info("%d log(s) com mais de %d dias apagados", apagados, config.log_dias_retencao)

    motivo = motivo_carga_completa(config, snapshot, forcar_completa)
    resumo = carga_completa(config, sankhya, snapshot, motivo) if motivo else incremental(config, sankhya, snapshot)
    log.info("Ciclo concluído em %.1fs", time.monotonic() - inicio)
    return resumo


def _num(n: int) -> str:
    return f"{n:,}".replace(",", ".")


def avisar_sucesso(config: cfg.Config, snapshot: Snapshot, resumo: Resumo, segundos: float) -> None:
    erro_anterior = snapshot.estado("erro_ativo")
    if erro_anterior:
        snapshot.banco.definir_estado("erro_ativo", "")
        telegram.enviar(config, telegram.titulo("✅", "voltou a funcionar") + "\nO último erro avisado foi resolvido.")
    if not resumo.relevante:
        return

    if resumo.alteracoes == 0:
        envio = "nenhum e-mail necessário"
    elif resumo.email_enviado:
        envio = f"e-mail enviado para {len(config.email_destinatarios)} destinatário(s)"
    else:
        envio = "⚠️ e-mail não configurado, alterações só no log"

    if resumo.completa:
        linhas = [
            telegram.titulo("🔄", "carga completa"),
            f"Motivo: {resumo.detalhe}",
            f"{_num(resumo.precos)} preços vigentes · {_num(resumo.alteracoes)} alteração(ões)",
        ]
    else:
        linhas = [
            telegram.titulo("✅", f"{_num(resumo.alteracoes)} preço(s) alterado(s)"),
            f"Versão nova da tabela: {resumo.detalhe}",
        ]
    linhas += [envio.capitalize(), f"⏱ {segundos:.1f}s".replace(".", ",")]
    telegram.enviar(config, "\n".join(linhas))


def _assinatura(erro: BaseException) -> str:
    # Pelo tipo do erro, não pelo texto, que costuma trazer horário ou id de requisição.
    return f"{type(erro).__module__}.{type(erro).__name__}"


def avisar_erro(config: cfg.Config, snapshot: Snapshot | None, erro: BaseException) -> None:
    """Avisa só o primeiro erro: com o Sankhya fora, o cron falharia a cada 10 minutos."""
    assinatura = _assinatura(erro)
    try:
        if snapshot and snapshot.estado("erro_ativo") == assinatura:
            log.info("Erro do mesmo tipo do último avisado; Telegram não notificado de novo")
            return
        if snapshot:
            snapshot.banco.definir_estado("erro_ativo", assinatura)
    except Exception:
        log.exception("Não foi possível consultar o último erro no banco; avisando mesmo assim")
    telegram.enviar(config, "\n".join([
        telegram.titulo("❌", "erro"),
        telegram.bloco_erro(erro),
        "Os próximos erros iguais não serão avisados; você recebe um aviso quando voltar a funcionar.",
    ]))


def avisar_deploy(
    config: cfg.Config, snapshot: Snapshot, resumo: Resumo | None, erro: BaseException | None, segundos: float,
) -> None:
    """Primeira execução após um deploy: e-mail para EMAIL_DEPLOY e Telegram, uma vez por commit."""
    assunto, texto, html = mensagem.deploy(
        config, resumo.precos if resumo else None, resumo.alteracoes if resumo else None, erro, segundos,
    )
    situacao_email = "e-mail de deploy: EMAIL_DEPLOY não configurado"
    if config.email_deploy:
        try:
            envio_email.enviar(config, assunto, texto, html, destinatarios=config.email_deploy)
            situacao_email = f"e-mail de deploy enviado para {', '.join(config.email_deploy)}"
        except envio_email.EmailErro as falha:
            log.error("Falha ao enviar e-mail de deploy: %s", falha)
            situacao_email = "⚠️ falha ao enviar o e-mail de deploy (ver log)"

    if erro:
        corpo = [telegram.titulo("🚀", f"deploy {config.render_git_commit[:7]} com erro"), telegram.bloco_erro(erro)]
    else:
        corpo = [
            telegram.titulo("🚀", f"deploy {config.render_git_commit[:7]}"),
            f"Carga completa: {_num(resumo.precos)} preços vigentes · {_num(resumo.alteracoes)} alteração(ões)",
        ]
    telegram.enviar(config, "\n".join(corpo + [situacao_email.capitalize(), f"⏱ {segundos:.1f}s".replace(".", ",")]))

    snapshot.banco.definir_estado("deploy_avisado", config.render_git_commit)
    # O aviso de deploy já cobre o erro (ou a recuperação): ajusta o controle de erros repetidos.
    snapshot.banco.definir_estado("erro_ativo", _assinatura(erro) if erro else "")


def novo_deploy(config: cfg.Config, snapshot: Snapshot) -> bool:
    if not config.render_git_commit:  # fora do Render
        return False
    try:
        return snapshot.estado("deploy_avisado") != config.render_git_commit
    except Exception:
        log.exception("Não foi possível verificar o último deploy avisado")
        return False


def executar(config: cfg.Config, sankhya: Sankhya, snapshot: Snapshot, forcar_completa: bool) -> bool:
    inicio = time.monotonic()
    deploy = novo_deploy(config, snapshot)
    resumo, erro = None, None
    try:
        resumo = ciclo(config, sankhya, snapshot, forcar_completa)
    except Exception as falha:
        log.exception("Falha no ciclo")
        erro = falha

    segundos = time.monotonic() - inicio
    try:
        if deploy:
            avisar_deploy(config, snapshot, resumo, erro, segundos)
        elif erro:
            avisar_erro(config, snapshot, erro)
        else:
            avisar_sucesso(config, snapshot, resumo, segundos)
    except Exception:
        log.exception("Falha ao enviar os avisos da execução")
    return erro is None


def _sinal(*_):
    global _parar
    _parar = True
    log.info("Sinal recebido; encerrando após o ciclo atual")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--loop", action="store_true", help="roda continuamente a cada INTERVALO_MINUTOS")
    parser.add_argument("--carga-completa", action="store_true", help="força a recarga de todos os preços vigentes")
    parser.add_argument("--testar-email", action="store_true", help="envia um e-mail de teste aos destinatários")
    parser.add_argument("--testar-telegram", action="store_true", help="envia um aviso de teste no Telegram")
    args = parser.parse_args()

    config = cfg.carregar()
    logs.configurar()

    if args.testar_email:
        try:
            envio_email.enviar(
                config,
                "Teste do monitor de preços do Sankhya",
                "Se você recebeu este e-mail, o envio pelo SMTP está funcionando.",
            )
        except envio_email.EmailErro as erro:
            log.error("%s", erro)
            return 1
        return 0

    if args.testar_telegram:
        if not config.telegram_configurado:
            log.error("Defina TELEGRAM_BOT_TOKEN e TELEGRAM_CHAT_ID")
            return 1
        return 0 if telegram.enviar(config, telegram.titulo("✅", "teste") + "\nAvisos do Telegram funcionando.") else 1

    try:
        banco = Banco(config.database_url)
        # Antes de criar/migrar as tabelas: a primeira carga pode passar dos 10 minutos do cron.
        if not banco.tentar_travar():
            log.info("Outra execução em andamento (ex.: primeira carga); saindo")
            return 0
        snapshot = Snapshot(banco)
        # Conexão separada: os logs gravam fora da transação do snapshot.
        logs.configurar(Banco(config.database_url))
    except Exception as erro:
        log.exception("Falha ao conectar no banco")
        avisar_erro(config, None, erro)
        return 1
    log.info("Banco: %s", "Postgres" if snapshot.banco.postgres else "SQLite local")
    sankhya = Sankhya(config)

    if not args.loop:
        return 0 if executar(config, sankhya, snapshot, args.carga_completa) else 1

    signal.signal(signal.SIGTERM, _sinal)
    signal.signal(signal.SIGINT, _sinal)
    intervalo = config.intervalo_minutos * 60
    log.info("Iniciando monitoramento a cada %d minuto(s)", config.intervalo_minutos)

    forcar = args.carga_completa
    while not _parar:
        proximo = time.monotonic() + intervalo
        # Erro em um ciclo (rede, Sankhya fora, etc.) não derruba o monitoramento.
        if executar(config, sankhya, snapshot, forcar):
            forcar = False
        while not _parar and time.monotonic() < proximo:
            time.sleep(1)

    log.info("Monitoramento encerrado")
    return 0


if __name__ == "__main__":
    sys.exit(main())

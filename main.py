"""Verifica alterações de preço de venda no Sankhya e avisa por e-mail.

Uso:
    python main.py                 # um ciclo (para usar com cron a cada 5 min)
    python main.py --loop          # fica rodando, um ciclo a cada INTERVALO_MINUTOS
    python main.py --testar-email  # envia um e-mail de teste aos destinatários
"""

import argparse
import fcntl
import logging
import signal
import sys
import time

from notifica_precos import config as cfg
from notifica_precos import envio_email, logs, mensagem
from notifica_precos.banco import Banco
from notifica_precos.sankhya import Sankhya
from notifica_precos.snapshot import Diferenca, Snapshot, de_registro

log = logging.getLogger("notifica_precos")

_parar = False


def ciclo(config: cfg.Config, sankhya: Sankhya, snapshot: Snapshot) -> None:
    inicio = time.monotonic()
    apagados = logs.limpar_antigos(snapshot.banco, config.log_dias_retencao)
    if apagados:
        log.info("%d log(s) com mais de %d dias apagados", apagados, config.log_dias_retencao)
    registros = sankhya.precos_venda()
    # Registros vêm ordenados por NUTAB; em caso de chave repetida fica a versão mais nova.
    atuais = {p.chave: p for p in map(de_registro, registros)}
    log.info("%d preços lidos do Sankhya", len(atuais))

    if snapshot.vazio():
        snapshot.salvar(Diferenca([], list(atuais.values()), []), notificado=False)
        log.info("Primeira execução: foto inicial salva, nada a notificar")
        return

    dif = snapshot.comparar(atuais)
    alteracoes = dif.alteracoes
    if dif.removidos:
        log.info("%d item(ns) saíram da consulta (inativados ou removidos da tabela)", len(dif.removidos))
    if not alteracoes:
        snapshot.salvar(dif, notificado=False)
        log.info("Nenhuma alteração de preço (%.1fs)", time.monotonic() - inicio)
        return

    for a in alteracoes:
        log.info(
            "ALTERACAO tab=%s prod=%s local=%s controle=%r nutab=%s→%s valor=%s→%s %s",
            a.atual.codtab, a.atual.codprod, a.atual.codlocal, a.atual.controle,
            a.anterior.nutab if a.anterior else "-", a.atual.nutab,
            a.anterior.vlrvenda if a.anterior else "-", a.atual.vlrvenda, a.atual.descrprod,
        )

    notificado = False
    if config.email_configurado:
        # Se o envio falhar, a foto não é atualizada e a alteração é reenviada no próximo ciclo.
        envio_email.enviar(
            config,
            mensagem.assunto(alteracoes),
            mensagem.texto(alteracoes, config.max_itens_email),
            mensagem.html(alteracoes, config.max_itens_email),
            anexos=[(f"alteracoes_precos_{time.strftime('%Y%m%d_%H%M')}.csv",
                     mensagem.csv_completo(alteracoes), "text/csv")],
        )
        notificado = True
    else:
        log.warning("E-mail não configurado: alterações registradas apenas no log")

    snapshot.salvar(dif, notificado)
    log.info("%d alteração(ões) processada(s) (%.1fs)", len(alteracoes), time.monotonic() - inicio)


def _travar() -> object:
    """Impede duas execuções simultâneas (ex.: cron disparando com ciclo anterior ainda rodando)."""
    trava = open(cfg.RAIZ / ".notifica_precos.lock", "w")
    try:
        fcntl.flock(trava, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        log.warning("Outra execução em andamento; saindo")
        sys.exit(0)
    return trava


def _sinal(*_):
    global _parar
    _parar = True
    log.info("Sinal recebido; encerrando após o ciclo atual")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--loop", action="store_true", help="roda continuamente a cada INTERVALO_MINUTOS")
    parser.add_argument("--testar-email", action="store_true", help="envia um e-mail de teste aos destinatários")
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

    trava = _travar()  # noqa: F841 (mantida aberta até o fim do processo)
    # Conexões separadas: os logs gravam fora da transação do snapshot.
    snapshot = Snapshot(Banco(config.database_url))
    logs.configurar(Banco(config.database_url))
    log.info("Banco: %s", "Postgres" if snapshot.banco.postgres else "SQLite local")
    sankhya = Sankhya(config)

    if not args.loop:
        try:
            ciclo(config, sankhya, snapshot)
            return 0
        except Exception:
            log.exception("Falha no ciclo")
            return 1

    signal.signal(signal.SIGTERM, _sinal)
    signal.signal(signal.SIGINT, _sinal)
    intervalo = config.intervalo_minutos * 60
    log.info("Iniciando monitoramento a cada %d minuto(s)", config.intervalo_minutos)

    while not _parar:
        proximo = time.monotonic() + intervalo
        try:
            ciclo(config, sankhya, snapshot)
        except Exception:
            # Erro em um ciclo (rede, Sankhya fora, etc.) não derruba o monitoramento.
            log.exception("Falha no ciclo; nova tentativa em %d minuto(s)", config.intervalo_minutos)
        while not _parar and time.monotonic() < proximo:
            time.sleep(1)

    log.info("Monitoramento encerrado")
    return 0


if __name__ == "__main__":
    sys.exit(main())

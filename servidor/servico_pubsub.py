# -*- coding: utf-8 -*-
import redis
import json
import os
import threading
from typing import Callable, Dict, Any

# Configuração do Redis (mesma do ServicoCoordenacao)
REDIS_HOST = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT = int(os.environ.get("REDIS_PORT", 6379))

class ServicoPubSub:
    """
    Implementa o modelo Publisher-Subscriber usando Redis.
    Técnica: Uso da biblioteca 'redis-py' e do recurso nativo Pub/Sub do Redis.
    Justificativa: Redis é rápido, leve e já está sendo usado para coordenação (2PC),
    evitando a necessidade de mais uma dependência (ex: RabbitMQ ou Kafka).
    """
    
    def __init__(self):
        self.redis_client = redis.Redis(host=REDIS_HOST, port=REDIS_PORT, decode_responses=True)
        self.pubsub = self.redis_client.pubsub()
        self.thread = None
        self.callbacks: Dict[str, Callable[[Dict[str, Any]], None]] = {}
        
    def publicar(self, canal: str, evento: Dict[str, Any]):
        """Publica um evento em um canal específico."""
        mensagem = json.dumps(evento)
        self.redis_client.publish(canal, mensagem)
        
    def inscrever_e_ouvir(self, canal: str, callback: Callable[[Dict[str, Any]], None]):
        """
        Inscreve-se em um canal e inicia uma thread para ouvir as mensagens.
        Este método é mais adequado para o lado do servidor que precisa reagir a eventos.
        """
        self.callbacks[canal] = callback
        self.pubsub.subscribe(**{canal: self._handler_mensagem})
        
        if not self.thread or not self.thread.is_alive():
            self.thread = threading.Thread(target=self._run_thread, daemon=True)
            self.thread.start()

    def _handler_mensagem(self, mensagem):
        """Função de callback chamada quando uma mensagem é recebida."""
        if mensagem['type'] == 'message':
            try:
                canal = mensagem['channel']
                dados = json.loads(mensagem['data'])
                
                if canal in self.callbacks:
                    self.callbacks[canal](dados)
                
            except json.JSONDecodeError as e:
                print(f"Erro ao decodificar JSON da mensagem: {e}")
            except Exception as e:
                print(f"Erro no handler de mensagem: {e}")

    def _run_thread(self):
        """Loop principal da thread de escuta do Pub/Sub."""
        print("Thread de escuta do Pub/Sub iniciada...")
        # Ignora mensagens de 'subscribe' e 'unsubscribe'
        for item in self.pubsub.listen():
            if item['type'] == 'message':
                self._handler_mensagem(item)

    def fechar(self):
        """Fecha a conexão do Pub/Sub."""
        self.pubsub.close()
        # Não é necessário forçar o fim da thread, pois ela é daemon e fechará com o processo.

# --- Canais Padrão ---
CANAL_EVENTOS_GERAIS = "eventos_gerais"
CANAL_NOTIFICACOES_JOGADOR = "notificacoes_jogador_{id_jogador}"
CANAL_PARTIDA = "partida_{id_partida}"

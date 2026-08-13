AQL Vision — instalação no Raspberry Pi
========================================

1. Instalar a câmara e dependências:

   sudo apt update
   sudo apt install -y python3-picamera2 python3-opencv python3-requests

2. Copiar os ficheiros:

   sudo mkdir -p /opt/aql-vision /etc/aql-vision /var/lib/aql-vision/offline
   sudo cp aql_vision_raspberry_agent.py /opt/aql-vision/
   sudo cp aql-vision-agent.env.example /etc/aql-vision/agent.env
   sudo cp aql-vision-raspberry-agent.service /etc/systemd/system/

3. Editar o token exclusivo do dispositivo:

   sudo nano /etc/aql-vision/agent.env
   sudo chmod 600 /etc/aql-vision/agent.env

4. Testar manualmente:

   set -a
   source /etc/aql-vision/agent.env
   set +a
   python3 /opt/aql-vision/aql_vision_raspberry_agent.py

5. Ativar como serviço:

   sudo systemctl daemon-reload
   sudo systemctl enable --now aql-vision-raspberry-agent
   sudo systemctl status aql-vision-raspberry-agent

6. Consultar os registos:

   journalctl -u aql-vision-raspberry-agent -f

O token nunca deve ser colocado diretamente dentro do script Python.
O servidor guarda apenas o hash e limita esta credencial ao kit e à câmara.

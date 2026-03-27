# server.py - Para hospedar no Render.com
import os
import json
import time
import threading
from datetime import datetime, timedelta
from flask import Flask, request, jsonify
from flask_cors import CORS
from github import Github
import hashlib
import secrets

app = Flask(__name__)
CORS(app)

# Configurações do ambiente
GITHUB_TOKEN = os.environ.get('GITHUB_TOKEN')
GIST_ID = os.environ.get('GIST_ID')
MESSAGE_TTL_HOURS = 6  # Mensagens expiram após 6 horas

class MessageServer:
    def __init__(self):
        self.github = Github(GITHUB_TOKEN)
        self.gist = self.github.get_gist(GIST_ID)
        self.data = self.load_data()
        self.cleanup_thread = threading.Thread(target=self.cleanup_loop, daemon=True)
        self.cleanup_thread.start()
    
    def load_data(self):
        """Carrega dados do Gist"""
        try:
            content = self.gist.files['messages.json'].content
            return json.loads(content)
        except:
            # Estrutura inicial
            return {
                'users': {},
                'messages': [],
                'last_cleanup': datetime.now().isoformat()
            }
    
    def save_data(self):
        """Salva dados no Gist"""
        self.gist.edit(
            files={
                'messages.json': json.dumps(self.data, indent=2)
            }
        )
    
    def cleanup_loop(self):
        """Limpa mensagens antigas a cada hora"""
        while True:
            time.sleep(3600)
            self.cleanup_old_messages()
    
    def cleanup_old_messages(self):
        """Remove mensagens mais antigas que TTL"""
        cutoff = datetime.now() - timedelta(hours=MESSAGE_TTL_HOURS)
        
        self.data['messages'] = [
            msg for msg in self.data['messages']
            if datetime.fromisoformat(msg['timestamp']) > cutoff
        ]
        self.data['last_cleanup'] = datetime.now().isoformat()
        self.save_data()
    
    def register_user(self, name):
        """Registra um novo usuário"""
        user_id = secrets.token_hex(8)
        
        # Verifica se nome já existe
        for uid, user in self.data['users'].items():
            if user['name'].lower() == name.lower():
                return None, "Nome já está em uso"
        
        self.data['users'][user_id] = {
            'name': name,
            'created_at': datetime.now().isoformat(),
            'contacts': []
        }
        self.save_data()
        return user_id, "Usuário registrado com sucesso"
    
    def add_contact(self, user_id, contact_name):
        """Adiciona um contato"""
        if user_id not in self.data['users']:
            return False, "Usuário não encontrado"
        
        # Encontra o ID do contato pelo nome
        contact_id = None
        for uid, user in self.data['users'].items():
            if user['name'].lower() == contact_name.lower():
                contact_id = uid
                break
        
        if not contact_id:
            return False, "Contato não encontrado"
        
        if contact_id == user_id:
            return False, "Não é possível adicionar a si mesmo"
        
        contacts = self.data['users'][user_id]['contacts']
        if contact_id not in [c['id'] for c in contacts]:
            contacts.append({
                'id': contact_id,
                'name': self.data['users'][contact_id]['name'],
                'added_at': datetime.now().isoformat()
            })
            self.save_data()
            return True, "Contato adicionado"
        
        return False, "Contato já existe"
    
    def get_contacts(self, user_id):
        """Retorna lista de contatos do usuário"""
        if user_id not in self.data['users']:
            return []
        return self.data['users'][user_id]['contacts']
    
    def send_message(self, from_id, to_name, content):
        """Envia uma mensagem"""
        if from_id not in self.data['users']:
            return False, "Remetente não encontrado"
        
        # Encontra destinatário pelo nome
        to_id = None
        for uid, user in self.data['users'].items():
            if user['name'].lower() == to_name.lower():
                to_id = uid
                break
        
        if not to_id:
            return False, "Destinatário não encontrado"
        
        message = {
            'id': secrets.token_hex(16),
            'from_id': from_id,
            'from_name': self.data['users'][from_id]['name'],
            'to_id': to_id,
            'to_name': to_name,
            'content': content,
            'timestamp': datetime.now().isoformat(),
            'read': False
        }
        
        self.data['messages'].append(message)
        self.save_data()
        return True, "Mensagem enviada"
    
    def get_messages(self, user_id, contact_name=None):
        """Recupera mensagens do usuário"""
        if user_id not in self.data['users']:
            return []
        
        messages = []
        for msg in self.data['messages']:
            if msg['to_id'] == user_id or msg['from_id'] == user_id:
                if contact_name:
                    if msg['from_name'] == contact_name or msg['to_name'] == contact_name:
                        messages.append(msg)
                        # Marca como lida se for para o usuário
                        if msg['to_id'] == user_id and not msg['read']:
                            msg['read'] = True
                else:
                    messages.append(msg)
        
        # Ordena por timestamp
        messages.sort(key=lambda x: x['timestamp'])
        
        if contact_name:
            self.save_data()
        
        return messages
    
    def get_user_info(self, user_id):
        """Retorna informações do usuário"""
        if user_id not in self.data['users']:
            return None
        return self.data['users'][user_id]
    
    def get_user_by_name(self, name):
        """Encontra usuário pelo nome"""
        for uid, user in self.data['users'].items():
            if user['name'].lower() == name.lower():
                return uid, user
        return None, None

server = MessageServer()

@app.route('/register', methods=['POST'])
def register():
    data = request.json
    name = data.get('name', '').strip()
    
    if not name:
        return jsonify({'error': 'Nome é obrigatório'}), 400
    
    user_id, message = server.register_user(name)
    if user_id:
        return jsonify({'user_id': user_id, 'name': name, 'message': message})
    else:
        return jsonify({'error': message}), 400

@app.route('/login', methods=['POST'])
def login():
    data = request.json
    user_id = data.get('user_id', '').strip()
    
    user_info = server.get_user_info(user_id)
    if user_info:
        return jsonify({
            'user_id': user_id,
            'name': user_info['name'],
            'contacts': user_info['contacts']
        })
    else:
        return jsonify({'error': 'Usuário não encontrado'}), 404

@app.route('/user/<user_id>', methods=['GET'])
def get_user(user_id):
    user_info = server.get_user_info(user_id)
    if user_info:
        return jsonify({
            'user_id': user_id,
            'name': user_info['name'],
            'created_at': user_info['created_at']
        })
    return jsonify({'error': 'Usuário não encontrado'}), 404

@app.route('/user/by-name/<name>', methods=['GET'])
def get_user_by_name(name):
    user_id, user_info = server.get_user_by_name(name)
    if user_id:
        return jsonify({
            'user_id': user_id,
            'name': user_info['name'],
            'created_at': user_info['created_at']
        })
    return jsonify({'error': 'Usuário não encontrado'}), 404

@app.route('/contacts/<user_id>', methods=['GET'])
def get_contacts(user_id):
    contacts = server.get_contacts(user_id)
    return jsonify({'contacts': contacts})

@app.route('/contacts/add', methods=['POST'])
def add_contact():
    data = request.json
    user_id = data.get('user_id')
    contact_name = data.get('contact_name', '').strip()
    
    success, message = server.add_contact(user_id, contact_name)
    if success:
        return jsonify({'message': message, 'contacts': server.get_contacts(user_id)})
    return jsonify({'error': message}), 400

@app.route('/messages/send', methods=['POST'])
def send_message():
    data = request.json
    from_id = data.get('from_id')
    to_name = data.get('to_name', '').strip()
    content = data.get('content', '').strip()
    
    if not content:
        return jsonify({'error': 'Mensagem vazia'}), 400
    
    success, message = server.send_message(from_id, to_name, content)
    if success:
        return jsonify({'message': message})
    return jsonify({'error': message}), 400

@app.route('/messages/<user_id>', methods=['GET'])
def get_messages(user_id):
    contact_name = request.args.get('contact')
    messages = server.get_messages(user_id, contact_name)
    return jsonify({'messages': messages})

@app.route('/messages/unread/<user_id>', methods=['GET'])
def get_unread_count(user_id):
    messages = server.get_messages(user_id)
    unread = len([m for m in messages if m['to_id'] == user_id and not m['read']])
    return jsonify({'unread': unread})

@app.route('/cleanup', methods=['POST'])
def cleanup():
    server.cleanup_old_messages()
    return jsonify({'message': 'Cleanup executado'})

@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok', 'users': len(server.data['users'])})

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    app.run(host='0.0.0.0', port=port)

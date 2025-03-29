document.addEventListener('DOMContentLoaded', function() {
    // Elementi UI
    const conversation = document.getElementById('conversation');
    const userInput = document.getElementById('user-input');
    const sendButton = document.getElementById('send-btn');
    const sendIcon = document.getElementById('send-icon');
    const loadingIcon = document.getElementById('loading-icon');
    const clearButton = document.getElementById('clear-btn');
    const errorMessage = document.getElementById('error-message');
    const statusIndicator = document.getElementById('status-indicator');
    const modeDropdown = document.getElementById('modeDropdown');
    const feedbackCard = document.getElementById('feedback-card');
    const ratingStars = document.querySelectorAll('.star');
    const ratingText = document.getElementById('rating-text');
    const feedbackText = document.getElementById('feedback-text');
    const submitFeedback = document.getElementById('submit-feedback');
    
    // Variabili di stato
    let currentMode = 'standard';
    let clientId = generateClientId();
    let websocket = null;
    let websocketReconnectAttempts = 0;
    let lastQueryId = null;
    let isProcessing = false;
    
    // Configurazione Marked.js
    marked.setOptions({
        highlight: function(code, lang) {
            if (lang && hljs.getLanguage(lang)) {
                return hljs.highlight(code, { language: lang }).value;
            }
            return hljs.highlightAuto(code).value;
        },
        breaks: true,
        gfm: true
    });
    
    // Verifica lo stato dell'agente
    checkAgentStatus();
    
    // Imposta i gestori di eventi
    setupEventListeners();
    
    // Connetti al WebSocket
    connectWebSocket();
    
    // FUNZIONI
    
    // Verifica lo stato dell'agente
	function checkAgentStatus() {
		fetch('/status')
			.then(response => response.json())
			.then(data => {
				const statusIndicator = document.getElementById('status-indicator');
				
				// Aggiorna la UI in base allo stato del backend
				if (data.backend && data.backend.ready) {
					statusIndicator.innerHTML = '<span class="text-success">●</span> Pronto';
					statusIndicator.classList.remove('initializing');
					statusIndicator.classList.add('ready');
					statusIndicator.classList.remove('error');
				} else if (data.backend && data.backend.error) {
					statusIndicator.innerHTML = '<span class="text-danger">●</span> Errore';
					statusIndicator.classList.remove('initializing');
					statusIndicator.classList.remove('ready');
					statusIndicator.classList.add('error');
				} else {
					// Continua a verificare lo stato ogni 5 secondi
					statusIndicator.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span> Inizializzazione...';
					statusIndicator.classList.add('initializing');
					setTimeout(checkAgentStatus, 5000);
				}
			})
			.catch(err => {
				console.error('Errore nel controllo stato:', err);
				const statusIndicator = document.getElementById('status-indicator');
				statusIndicator.innerHTML = '<span class="text-danger">●</span> Errore';
				statusIndicator.classList.add('error');
			});
	}
    
    // Imposta i gestori di eventi
    function setupEventListeners() {
        // Invio del messaggio
        sendButton.addEventListener('click', sendMessage);
        userInput.addEventListener('keydown', function(e) {
            if (e.key === 'Enter' && !e.shiftKey) {
                e.preventDefault();
                sendMessage();
            }
        });
        
        // Pulizia conversazione
        clearButton.addEventListener('click', clearConversation);
        
        // Cambio modalità
        document.querySelectorAll('.dropdown-item').forEach(item => {
            item.addEventListener('click', function(e) {
                e.preventDefault();
                const mode = this.getAttribute('data-mode');
                changeMode(mode);
                
                // Aggiorna UI
                document.querySelectorAll('.dropdown-item').forEach(i => i.classList.remove('active'));
                this.classList.add('active');
                modeDropdown.textContent = `Modalità: ${mode === 'standard' ? 'Standard' : 'Soluzione Completa'}`;
            });
        });
        
        // Sistema di valutazione
        ratingStars.forEach(star => {
            star.addEventListener('click', function() {
                const rating = parseInt(this.getAttribute('data-rating'));
                selectRating(rating);
            });
        });
        
        // Invio feedback
        submitFeedback.addEventListener('click', sendFeedback);
    }
    
    // Genera un ID cliente univoco
    function generateClientId() {
        return 'client_' + Math.random().toString(36).substring(2, 15);
    }
    
    // Connetti al WebSocket
    function connectWebSocket() {
        const protocol = window.location.protocol === 'https:' ? 'wss' : 'ws';
        const wsUrl = `${protocol}://${window.location.host}/ws/${clientId}`;
        
        websocket = new WebSocket(wsUrl);
        
        websocket.onopen = function() {
            console.log('WebSocket connesso');
            websocketReconnectAttempts = 0;
            errorMessage.classList.add('d-none');
        };
        
        websocket.onmessage = function(event) {
            const message = JSON.parse(event.data);
            handleWebSocketMessage(message);
        };
        
        websocket.onclose = function() {
            console.log('WebSocket disconnesso');
			
			if (isProcessing) {
				setProcessingState(false);
			}
            
            // Tentativo di riconnessione con backoff esponenziale
            if (websocketReconnectAttempts < 5) {
                const delay = Math.pow(2, websocketReconnectAttempts) * 1000;
                websocketReconnectAttempts++;
                
                setTimeout(() => {
                    console.log(`Tentativo di riconnessione ${websocketReconnectAttempts}...`);
                    connectWebSocket();
                }, delay);
            } else {
                errorMessage.textContent = 'Connessione persa. Ricarica la pagina per riprovare.';
                errorMessage.classList.remove('d-none');
            }
        };
        
        websocket.onerror = function(error) {
            console.error('Errore WebSocket:', error);
			
			// Ripristina sempre lo stato dell'interfaccia in caso di errore
			if (isProcessing) {
				setProcessingState(false);
			}
			
            errorMessage.textContent = 'Errore di connessione. Ricarica la pagina per riprovare.';
            errorMessage.classList.remove('d-none');
        };
    }
    
    // Gestisci i messaggi WebSocket
	function handleWebSocketMessage(message) {
		switch (message.type) {
			case 'user':
				addUserMessage(message.content);
				break;
			case 'assistant':
				addAssistantMessage(message.content);
				// Assicurati di ripristinare lo stato qui
				setProcessingState(false);
				showFeedbackCard();
				break;
			case 'status':
				addStatusMessage(message.content);
				break;
			case 'error':
				addErrorMessage(message.content);
				// Ripristina sempre lo stato anche in caso di errore
				setProcessingState(false);
				break;
			default:
				console.warn('Tipo di messaggio sconosciuto:', message.type);
				// Ripristina lo stato anche per messaggi sconosciuti
				setProcessingState(false);
		}
		
		// Scorrimento automatico
		scrollToBottom();
	}
    
    // Invia messaggio al server
    function sendMessage() {
        const message = userInput.value.trim();
        
        if (message === '' || isProcessing) {
            return;
        }
        
        // Nascondi card feedback
        feedbackCard.classList.add('d-none');
		
		// Imposta il timeout di sicurezza
		setupSafetyTimeout();
        
        // Imposta stato elaborazione
        setProcessingState(true);
        
        // Invia al WebSocket
        if (websocket && websocket.readyState === WebSocket.OPEN) {
            websocket.send(JSON.stringify({
                query: message,
                type: currentMode
            }));
            
            // Pulisci input
            userInput.value = '';
            
            // Nascondi messaggio di benvenuto se presente
            const welcomeMessage = document.querySelector('.welcome-message');
            if (welcomeMessage) {
                welcomeMessage.remove();
            }
        } else {
            addErrorMessage('Connessione non disponibile. Ricarica la pagina per riprovare.');
            setProcessingState(false);
            
            // Tentativo di riconnessione
            connectWebSocket();
        }
    }
    
    // Aggiungi messaggio utente alla conversazione
    function addUserMessage(content) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message user-message';
        messageDiv.textContent = content;
        conversation.appendChild(messageDiv);
    }
    
    // Aggiungi messaggio assistente alla conversazione
    function addAssistantMessage(content) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message assistant-message';
        
        // Se il contenuto è un oggetto (soluzione completa)
        if (typeof content === 'object') {
            messageDiv.innerHTML = renderSolutionCard(content);
        } else {
            // Converti markdown in HTML
            messageDiv.innerHTML = marked.parse(content);
        }
        
        conversation.appendChild(messageDiv);
        
        // Applica syntax highlighting
        messageDiv.querySelectorAll('pre code').forEach((block) => {
            hljs.highlightElement(block);
        });
    }
    
    // Aggiungi messaggio di stato
    function addStatusMessage(content) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'status-message';
        messageDiv.textContent = content;
        conversation.appendChild(messageDiv);
    }
    
    // Aggiungi messaggio di errore
    function addErrorMessage(content) {
        const messageDiv = document.createElement('div');
        messageDiv.className = 'message error-message';
        messageDiv.textContent = content;
        conversation.appendChild(messageDiv);
    }
    
    // Renderizza card per soluzione completa
    function renderSolutionCard(solution) {
        let html = `
            <div class="solution-card">
                <div class="solution-header">${solution.title}</div>
                <div class="solution-body">
                    <div><strong>Riassunto:</strong> ${solution.summary}</div>
                    <div class="mt-3"><strong>Approccio:</strong></div>
                    <div>${marked.parse(solution.approach)}</div>
                    
                    <div class="pros-cons">
                        <div class="pros">
                            <strong>Vantaggi:</strong>
                            <ul>
                                ${solution.pros.map(pro => `<li>${pro}</li>`).join('')}
                            </ul>
                        </div>
                        <div class="cons">
                            <strong>Limitazioni:</strong>
                            <ul>
                                ${solution.cons.map(con => `<li>${con}</li>`).join('')}
                            </ul>
                        </div>
                    </div>
        `;
        
        // Aggiungi soluzioni di codice
        if (solution.code_solutions && solution.code_solutions.length > 0) {
            solution.code_solutions.forEach(codeSolution => {
                html += `
                    <div class="code-solution">
                        <h5>${codeSolution.description}</h5>
                        <div><strong>Linguaggio:</strong> ${codeSolution.language}</div>
                        <div><strong>Prerequisiti:</strong></div>
                        <ul>
                            ${codeSolution.prerequisites.map(prereq => `<li>${prereq}</li>`).join('')}
                        </ul>
                        <div><strong>Codice:</strong></div>
                        <pre><code class="${getLanguageClass(codeSolution.language)}">${escapeHtml(codeSolution.code)}</code></pre>
                    </div>
                `;
            });
        }
        
        // Aggiungi riferimenti
        if (solution.references && solution.references.length > 0) {
            html += `
                <div class="references">
                    <strong>Riferimenti:</strong>
                    <ul>
                        ${solution.references.map(ref => `<li><a href="${ref}" target="_blank">${ref}</a></li>`).join('')}
                    </ul>
                </div>
            `;
        }
        
        html += `
                </div>
            </div>
        `;
        
        return html;
    }
    
    // Determina la classe di linguaggio per syntax highlighting
    function getLanguageClass(language) {
        const languageMap = {
            'Apex': 'java',
            'JavaScript': 'javascript',
            'HTML': 'xml',
            'CSS': 'css',
            'JavaScript/HTML': 'javascript',
            'Configurazione': 'plaintext'
        };
        
        return languageMap[language] || 'plaintext';
    }
    
    // Escape HTML per evitare problemi con il codice
    function escapeHtml(text) {
        const div = document.createElement('div');
        div.textContent = text;
        return div.innerHTML;
    }
    
    // Cambia modalità di risposta
    function changeMode(mode) {
        currentMode = mode;
    }
    
    // Imposta lo stato di elaborazione
	function setProcessingState(processing) {
		isProcessing = processing;
		
		if (processing) {
			sendIcon.classList.add('d-none');
			loadingIcon.classList.remove('d-none');
			userInput.disabled = true;
			sendButton.disabled = true;
		} else {
			// Importante: riabilita l'input
			sendIcon.classList.remove('d-none');
			loadingIcon.classList.add('d-none');
			userInput.disabled = false;
			sendButton.disabled = false;
			
			// Debug: verifica che questi elementi esistano
			console.log("Riabilito input:", userInput);
			console.log("Riabilito button:", sendButton);
		}
	}
    
    // Scorrimento automatico verso il basso
    function scrollToBottom() {
        conversation.scrollTop = conversation.scrollHeight;
    }
    
    // Pulisci conversazione
    function clearConversation() {
        // Rimuovi tutti i messaggi
        conversation.innerHTML = `
            <div class="welcome-message">
                <h4>Benvenuto nel tuo assistente AI per Salesforce!</h4>
                <p>Sono qui per aiutarti a risolvere problemi tecnici e fornire soluzioni a requisiti di business su Salesforce.</p>
                <p>Puoi chiedermi:</p>
                <ul>
                    <li>Come implementare funzionalità specifiche</li>
                    <li>Best practices per configurazioni</li>
                    <li>Soluzioni tecniche per requisiti di business</li>
                    <li>Esempi di codice Apex, Lightning o configurazioni</li>
                </ul>
                <p class="small text-muted">Scegli la modalità "Soluzione Completa" dal menu in alto per ottenere risposte più dettagliate con codice e approcci alternativi.</p>
            </div>
        `;
        
        // Nascondi card feedback
        feedbackCard.classList.add('d-none');
        
        // Reset valutazione
        resetRating();
    }
    
    // Mostra card feedback
    function showFeedbackCard() {
        feedbackCard.classList.remove('d-none');
        resetRating();
    }
    
    // Seleziona valutazione
    function selectRating(rating) {
        // Reset precedente
        resetRating();
        
        // Seleziona stelle
        for (let i = 0; i < rating; i++) {
            ratingStars[i].classList.add('selected');
        }
        
        // Aggiorna testo
        const ratingTexts = [
            "Molto deludente",
            "Deludente",
            "Accettabile",
            "Buono",
            "Eccellente"
        ];
        
        ratingText.textContent = ratingTexts[rating - 1];
        
        // Memorizza rating corrente
        ratingText.dataset.rating = rating;
    }
    
    // Reset valutazione
    function resetRating() {
        ratingStars.forEach(star => star.classList.remove('selected'));
        ratingText.textContent = "Seleziona una valutazione";
        delete ratingText.dataset.rating;
        feedbackText.value = '';
    }
    
    // Invia feedback
    function sendFeedback() {
        const rating = parseInt(ratingText.dataset.rating || 0);
        
        if (rating === 0) {
            alert("Per favore seleziona una valutazione.");
            return;
        }
        
        // Prepara dati
        const feedbackData = {
            query_id: lastQueryId || 'unknown',
            rating: rating,
            feedback_text: feedbackText.value.trim()
        };
        
        // Invia feedback
        fetch('/api/feedback', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json'
            },
            body: JSON.stringify(feedbackData)
        })
        .then(response => response.json())
        .then(data => {
            // Nascondi card
            feedbackCard.classList.add('d-none');
            
            // Mostra conferma
            addStatusMessage("Grazie per il tuo feedback!");
            
            // Reset
            resetRating();
        })
        .catch(error => {
            console.error('Errore invio feedback:', error);
            alert("Si è verificato un errore durante l'invio del feedback. Riprova più tardi.");
        });
    }
    
    // Mostra errore
    function showError(message) {
        errorMessage.textContent = message;
        errorMessage.classList.remove('d-none');
    }
	
	// Handler per errori imprevisti
	window.addEventListener('error', function(event) {
		console.error('Errore globale rilevato:', event.error);
		
		// Ripristina lo stato dell'interfaccia in caso di errore
		if (isProcessing) {
			console.log("Ripristino stato UI dopo errore");
			setProcessingState(false);
		}
	});

	// Aggiungi anche un timeout di sicurezza
	function setupSafetyTimeout() {
		if (isProcessing) {
			// Se dopo 60 secondi l'elaborazione è ancora in corso, ripristina l'interfaccia
			setTimeout(function() {
				if (isProcessing) {
					console.log("Timeout di sicurezza: ripristino interfaccia");
					addErrorMessage("La richiesta sta impiegando troppo tempo. L'interfaccia è stata ripristinata.");
					setProcessingState(false);
				}
			}, 60000); // 60 secondi
		}
	}
});
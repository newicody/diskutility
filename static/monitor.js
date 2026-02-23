const socket = io();

// État global
const AppState = {
    activeTasks: [],
    charts: {},
    currentChartType: 'read'
};

// Interface utilisateur
const Backup = {
    _taskId: null,       // ID de la tâche toolbox en cours

loadOptions: (device, container) => {
    container.innerHTML = `
        <div style="padding:15px; background:var(--bg); border-radius:8px;">
            <h4>Options de sauvegarde pour ${device}</h4>
            <form onsubmit="Backup.startFromPartition(event, '${device}')">
                <div class="form-group">
                    <label>Destination:</label>
                    <input type="text" id="dest-${device}" class="form-control" 
                           placeholder="/chemin/vers/sauvegarde.img" required>
                </div>
                
                <div class="form-group">
                    <label>Taille de bloc:</label>
                    <select id="bs-${device}" class="form-control">
                        <option value="4M">4 Mo (Recommandé)</option>
                        <option value="1M">1 Mo</option>
                        <option value="64K">64 Ko</option>
                    </select>
                </div>
                
                <div class="checkbox-group">
                    <label>
                        <input type="checkbox" id="noerror-${device}" checked> 
                        Ignorer erreurs lecture
                    </label>
                    <label>
                        <input type="checkbox" id="sync-${device}" checked> 
                        Synchroniser
                    </label>
                </div>
                
                <button type="submit" class="btn-primary">🚀 Démarrer</button>
            </form>
        </div>
    `;
},

startFromPartition: (event, device) => {
    event.preventDefault();
    
    const destination = document.getElementById(`dest-${device}`).value;
    const bs = document.getElementById(`bs-${device}`).value;
    
    let conv = [];
    if (document.getElementById(`noerror-${device}`).checked) conv.push('noerror');
    if (document.getElementById(`sync-${device}`).checked) conv.push('sync');
    
    const payload = {
        source: device,
        destination: destination,
        bs: bs,
        conv: conv.join(','),
        status: 'progress'
    };
    
    fetch('/start_backup', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(payload)
    }).then(response => {
        if (response.ok) {
            Backup._taskId = Toolbox.addInstantTask(`Sauvegarde ${device}`, `→ ${destination}`);
            UI.showNotification('Sauvegarde démarrée', 'success');
        }
    });
},

toggleExpand: (row, device) => {
    const detailsRow = document.getElementById(`details-${device}`);
    const isVisible = detailsRow.style.display !== 'none';
    
    // Fermer tous les autres détails
    document.querySelectorAll('.partition-details').forEach(el => {
        el.style.display = 'none';
    });
    
    if (!isVisible) {
        detailsRow.style.display = 'table-row';
        Backup.loadOptions(device, detailsRow.querySelector('.partition-expanded'));
    }
},

    showOptions: async (device) => {
        document.getElementById('backup-source').value = device;
        document.getElementById('backup-source-display').textContent = device;
        
        // Charger la liste des disques disponibles
        try {
            const response = await fetch('/get_backup_disks');
            const disks = await response.json();
            
            const select = document.getElementById('backup-disks');
            select.innerHTML = '<option value="">Choisir un disque de destination...</option>';
            
            disks.forEach(disk => {
                if (disk.name !== device.replace('/dev/', '')) {
                    select.innerHTML += `<option value="/dev/${disk.name}">${disk.name} - ${disk.size} (${disk.model})</option>`;
                }
            });
        } catch (error) {
            console.error('Erreur chargement disques:', error);
        }
        
        document.getElementById('backup-modal').style.display = 'flex';
        document.getElementById('backup-progress').style.display = 'none';
    },
    
    closeModal: () => {
        document.getElementById('backup-modal').style.display = 'none';
    },
    
    start: async (event) => {
        event.preventDefault();
        
        const source = document.getElementById('backup-source').value;
        const destination = document.getElementById('backup-destination').value;
        const bs = document.getElementById('backup-bs').value;
        
        // Construire l'option conv
        let conv = [];
        if (document.getElementById('backup-noerror').checked) conv.push('noerror');
        if (document.getElementById('backup-sync').checked) conv.push('sync');
        
        const payload = {
            source: source,
            destination: destination,
            bs: bs,
            conv: conv.join(','),
            status: document.getElementById('backup-progress').checked ? 'progress' : 'none'
        };
        
        try {
            const response = await fetch('/start_backup', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
            
            if (response.ok) {
                Backup._taskId = Toolbox.addInstantTask(`Sauvegarde ${source}`, `→ ${destination}`);
                UI.showNotification('Sauvegarde démarrée', 'success');
                document.getElementById('backup-progress').style.display = 'block';
            } else {
                UI.showNotification('Erreur au démarrage', 'error');
            }
        } catch (error) {
            UI.showNotification('Erreur réseau', 'error');
        }
    }
};



const UI = {
    toggleTasks: () => {
        const popup = document.getElementById('active-tasks');
        if (!popup) return;
        
        popup.classList.toggle('show');
        
        // Mettre à jour l'icône du bouton
        const btn = document.getElementById('task-status-btn');
        if (popup.classList.contains('show')) {
            btn.innerHTML = '🔽 Tâches en cours';
        } else {
            btn.innerHTML = '🔼 Tâches en cours';
        }
    },

toggleDiskExpand: (card, deviceName, forceClose = false) => {
    const grid = card.closest('.disk-grid');
    const expandIcon = card.querySelector('.expand-icon');
    const wasExpanded = card.classList.contains('expanded');

    // --- Replier ---
    if (forceClose || wasExpanded) {
        card.classList.remove('expanded');
        if (expandIcon) expandIcon.innerHTML = '🔽';

        // Remettre la carte à sa position d'origine (mémorisée)
        const originalIndex = parseInt(card.dataset.originalIndex ?? '-1');
        if (grid && originalIndex >= 0) {
            const siblings = Array.from(grid.children).filter(c => c !== card);
            const ref = siblings[originalIndex] || null;
            grid.insertBefore(card, ref);
        }
        delete card.dataset.originalIndex;
        return;
    }

    // --- Déplier ---
    // Fermer toute autre carte déjà dépliée d'abord
    grid?.querySelectorAll('.disk-card.expanded').forEach(c => {
        c.classList.remove('expanded');
        const ic = c.querySelector('.expand-icon');
        if (ic) ic.innerHTML = '🔽';
        const idx = parseInt(c.dataset.originalIndex ?? '-1');
        if (idx >= 0) {
            const siblings = Array.from(grid.children).filter(x => x !== c);
            grid.insertBefore(c, siblings[idx] || null);
        }
        delete c.dataset.originalIndex;
    });

    // Mémoriser la position courante dans la grille
    const currentIndex = Array.from(grid?.children ?? []).indexOf(card);
    card.dataset.originalIndex = currentIndex;

    // Déplacer en premier dans la grille → grid-column:1/-1 s'applique proprement
    grid?.insertBefore(card, grid.firstChild);
    card.classList.add('expanded');
    if (expandIcon) expandIcon.innerHTML = '🔼';

    UI.loadDiskDetails(card, deviceName);
},

loadDiskDetails: async (card, deviceName) => {
    // Utiliser la div .disk-details déjà présente dans le HTML (ou créer si absente)
    let detailsDiv = card.querySelector('.disk-details');
    // Si déjà chargé (a du contenu), ne pas recharger
    if (detailsDiv && detailsDiv.dataset.loaded === '1') return;
    if (!detailsDiv) {
        detailsDiv = document.createElement('div');
        detailsDiv.className = 'disk-details';
        card.appendChild(detailsDiv);
    }

    try {
        const response = await fetch(`/get_disk_details/${deviceName}`);
        const data = await response.json();
        
        // Construire le HTML des détails COMPLETS (pas juste 5 attributs)
        let attributesHtml = '';
        if (data.attributes && data.attributes.length > 0) {
            attributesHtml = data.attributes.map(attr => `
                <div class="attribute-item ${attr.critical ? 'critical' : ''}">
                    <span class="attribute-name">${attr.name}</span>
                    <span class="attribute-value">${attr.raw}</span>
                </div>
            `).join('');
        }
        
        let alertsHtml = '';
        if (data.alerts && data.alerts.length > 0) {
            alertsHtml = data.alerts.map(a => `
                <div class="attribute-item critical tooltip" data-tooltip="${a.explication}">
                    <span class="attribute-name">⚠️</span>
                    <span class="attribute-value">${a.alert}</span>
                </div>
            `).join('');
        } else {
            alertsHtml = '<p>Aucune alerte</p>';
        }
        
        let partitionsHtml = '';
        if (data.partitions && data.partitions.length > 0) {
            partitionsHtml = `
                <div class="disk-details-section full-width">
                    <h4>📂 Partitions</h4>
                    <div class="table-responsive">
                        <table class="disk-detail-table">
                            <thead>
                                <tr>
                                    <th>Partition</th>
                                    <th>Montage</th>
                                    <th>Format</th>
                                    <th>Taille</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${data.partitions.map(p => `
                                    <tr>
                                        <td><code>${p.name}</code></td>
                                        <td>${p.mountpoint || '-'}</td>
                                        <td>${p.fstype || '-'}</td>
                                        <td>${p.size || '-'}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                </div>
            `;
        }
        
        let zfsHtml = '';
        if (data.zfs_pools && data.zfs_pools.length > 0) {
            zfsHtml = `
                <div class="disk-details-section full-width">
                    <h4>🛡️ Pools ZFS associés</h4>
                    ${data.zfs_pools.map(pool => `
                        <div class="zfs-pool" style="margin-bottom:10px;">
                            <div class="zfs-header">
                                <strong>${pool.name}</strong>
                                <span class="badge ${pool.health === 'ONLINE' ? 'bg-success' : 'bg-danger'}">${pool.health}</span>
                            </div>
                            <div class="zfs-stat">Capacité: ${pool.alloc} / ${pool.size} (${pool.cap}%)</div>
                        </div>
                    `).join('')}
                </div>
            `;
        }
        
        detailsDiv.innerHTML = `
            <div class="disk-details-grid">
                <div class="disk-details-section">
                    <h4>📊 Informations générales</h4>
                    <div class="attribute-item">
                        <span class="attribute-name">Modèle</span>
                        <span class="attribute-value">${data.model || 'N/A'}</span>
                    </div>
                    <div class="attribute-item">
                        <span class="attribute-name">Type</span>
                        <span class="attribute-value">${data.nature || 'N/A'}</span>
                    </div>
                    <div class="attribute-item">
                        <span class="attribute-name">Taille</span>
                        <span class="attribute-value">${data.size || 'N/A'}</span>
                    </div>
                    <div class="attribute-item">
                        <span class="attribute-name">Utilisation</span>
                        <span class="attribute-value">${data.usage || 'N/A'}</span>
                    </div>
                    <div class="attribute-item">
                        <span class="attribute-name">Température</span>
                        <span class="attribute-value">${data.temp || 'N/A'}°C</span>
                    </div>
                </div>
                
                <div class="disk-details-section">
                    <h4>⚠️ Alertes</h4>
                    ${alertsHtml}
                </div>
                
                <div class="disk-details-section full-width">
                    <h4>🔍 Attributs SMART (${data.attributes.length})</h4>
                    <div class="disk-detail-attributes">
                        ${attributesHtml}
                    </div>
                </div>
                
                ${partitionsHtml}
                ${zfsHtml}
            </div>
        `;
        
        detailsDiv.dataset.loaded = '1';
        // card.appendChild(detailsDiv) supprimé — div déjà dans le DOM via le template
    } catch (error) {
        console.error('Erreur chargement détails:', error);
    }
},

openDiskDetailModal: async (deviceName) => {
    try {
        // Récupérer toutes les données du disque
        const response = await fetch(`/get_disk_details/${deviceName}`);
        const data = await response.json();
        
        const modal = document.getElementById('disk-detail-modal');
        const content = document.getElementById('disk-detail-content');
        
        // Construire le HTML
        let html = `
            <div class="disk-detail-section">
                <h4>📊 Informations générales</h4>
                <table class="disk-detail-table">
                    <tr><th>Modèle</th><td>${data.model || 'N/A'}</td></tr>
                    <tr><th>Type</th><td>${data.nature || 'N/A'}</td></tr>
                    <tr><th>Taille</th><td>${data.size || 'N/A'}</td></tr>
                    <tr><th>Utilisation</th><td>${data.usage || 'N/A'}</td></tr>
                    <tr><th>Température</th><td>${data.temp || 'N/A'}°C</td></tr>
                </table>
            </div>
            
            <div class="disk-detail-section">
                <h4>⚠️ Alertes SMART</h4>
                ${data.alerts && data.alerts.length > 0 ? 
                    `<ul class="alert-list">
                        ${data.alerts.map(a => `<li class="tooltip" data-tooltip="${a.explication}">${a.alert}</li>`).join('')}
                    </ul>` : 
                    '<p>Aucune alerte</p>'}
            </div>
        `;
        
        // Ajouter les partitions
        if (data.partitions && data.partitions.length > 0) {
            html += `
                <div class="disk-detail-section full-width">
                    <h4>📂 Partitions</h4>
                    <div class="table-responsive">
                        <table class="disk-detail-table">
                            <thead>
                                <tr>
                                    <th>Partition</th>
                                    <th>Montage</th>
                                    <th>Format</th>
                                    <th>Taille</th>
                                    <th>Utilisation</th>
                                </tr>
                            </thead>
                            <tbody>
                                ${data.partitions.map(p => `
                                    <tr>
                                        <td><code>${p.name}</code></td>
                                        <td>${p.mountpoint || '-'}</td>
                                        <td>${p.fstype || '-'}</td>
                                        <td>${p.size || '-'}</td>
                                        <td>${p.use || '-'}</td>
                                    </tr>
                                `).join('')}
                            </tbody>
                        </table>
                    </div>
                </div>
            `;
        }
        
        // Ajouter les attributs SMART
        if (data.attributes && data.attributes.length > 0) {
            html += `
                <div class="disk-detail-section full-width">
                    <h4>🔍 Attributs SMART</h4>
                    <div class="disk-detail-attributes">
                        ${data.attributes.map(attr => `
                            <div class="attribute-item ${attr.critical ? 'critical' : ''}">
                                <div class="attribute-name">${attr.name}</div>
                                <div class="attribute-value">
                                    <span>Valeur: ${attr.value}</span>
                                    <span class="attribute-raw">${attr.raw}</span>
                                </div>
                            </div>
                        `).join('')}
                    </div>
                </div>
            `;
        }
        
        // Ajouter les pools ZFS si existent
        if (data.zfs_pools && data.zfs_pools.length > 0) {
            html += `
                <div class="disk-detail-section full-width">
                    <h4>🛡️ Pools ZFS associés</h4>
                    ${data.zfs_pools.map(pool => `
                        <div class="zfs-pool" style="margin-bottom:10px;">
                            <div class="zfs-header">
                                <strong>${pool.name}</strong>
                                <span class="badge ${pool.health === 'ONLINE' ? 'bg-success' : 'bg-danger'}">${pool.health}</span>
                            </div>
                            <div class="zfs-stat">Capacité: ${pool.alloc} / ${pool.size} (${pool.cap}%)</div>
                        </div>
                    `).join('')}
                </div>
            `;
        }
        
        content.innerHTML = html;
        document.getElementById('disk-detail-title').innerHTML = `💾 Détails du disque ${deviceName}`;
        modal.style.display = 'flex';
        
    } catch (error) {
        console.error('Erreur chargement détails disque:', error);
        UI.showNotification('Erreur chargement des détails', 'error');
    }
},

    openModal: (id) => {
        const modal = document.getElementById(id);
        if (modal) modal.style.display = 'flex';
    },

    closeModal: (id) => {
        const modal = document.getElementById(id);
        if (modal) modal.style.display = 'none';
    },

    refresh: () => {
        // Plus de reload de page — les mises à jour sont gérées par SocketIO et DOM
        // Utilisé uniquement pour compatibilité (ne pas supprimer les appels)
    },

    openDiskModal: async (deviceName) => {
        try {
            // Récupérer la note existante
            const response = await fetch(`/get_disk_notes/${deviceName}`);
            const data = await response.json();
            
            const modal = document.getElementById('disk-modal');
            modal.innerHTML = `
                <div class="modal-content card">
                    <div class="modal-header">
                        <h3>📝 Notes pour ${deviceName}</h3>
                        <button class="close-btn" onclick="UI.closeModal('disk-modal')">&times;</button>
                    </div>
                    <textarea id="disk-note-text" 
                        style="width:100%; height:150px; margin:15px 0; padding:10px; border:1px solid #ddd; border-radius:4px;"
                        placeholder="Ajoutez vos notes ici...">${data.note || ''}</textarea>
                    <div class="modal-footer">
                        <button class="btn-primary" onclick="UI.saveDiskNote('${deviceName}')">💾 Sauvegarder</button>
                        <button class="btn-sm" onclick="UI.closeModal('disk-modal')">Annuler</button>
                    </div>
                </div>
            `;
            modal.style.display = 'flex';
        } catch (error) {
            console.error('Erreur chargement note:', error);
        }
    },

    saveDiskNote: async (deviceName) => {
        const text = document.getElementById('disk-note-text').value;
        const taskId = Toolbox.addInstantTask(`Note disque ${deviceName}`);
        try {
            const response = await fetch('/save_disk_note', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify({device: deviceName, note: text})
            });
            
            if (response.ok) {
                Toolbox.finishInstantTask(taskId, 'Finished', 'Note sauvegardée');
                UI.showNotification('Note sauvegardée !', 'success');
                UI.closeModal('disk-modal');
            } else {
                Toolbox.finishInstantTask(taskId, 'Error', 'Erreur serveur');
                UI.showNotification('Erreur lors de la sauvegarde', 'error');
            }
        } catch (error) {
            Toolbox.finishInstantTask(taskId, 'Error', error.message);
            UI.showNotification('Erreur réseau', 'error');
        }
    },

    showNotification: (message, type = 'info') => {
        const notification = document.createElement('div');
        notification.className = `notification notification-${type}`;
        notification.innerHTML = message;
        notification.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 15px 20px;
            background: ${type === 'success' ? '#2ecc71' : type === 'error' ? '#e74c3c' : '#3498db'};
            color: white;
            border-radius: 5px;
            z-index: 10002;
            animation: slideIn 0.3s ease;
        `;
        document.body.appendChild(notification);
        
        setTimeout(() => {
            notification.style.animation = 'slideOut 0.3s ease';
            setTimeout(() => notification.remove(), 300);
        }, 3000);
    },

    updateActiveTasks: (tasks) => {
        // Mise à jour des tâches actives sans écraser l'historique toolbox
        tasks.forEach(task => {
            const existing = Toolbox.taskHistory.find(t => t.id === task.id);
            if (!existing) {
                Toolbox.handleProgressUpdate({
                    ...task,
                    status: 'Running'
                });
            } else if (existing.status === 'Running') {
                existing.progress = task.progress;
                existing.current_op = task.current_op || existing.current_op;
                Toolbox.renderHistory();
            }
        });
    }
};

// Benchmark engine
const Bench = {
    start: async (payload) => {
        try {
            const response = await fetch('/start_test', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(payload)
            });
            
            if (response.ok) {
                const startData = await response.json();
                UI.showNotification('Test démarré — suivi dans la toolbox', 'success');
                Toolbox.open();
                // Ajouter immédiatement la carte dans la liste
                if (startData.id) {
                    ReportsList.addRunning(startData.id, payload.name || 'Test');
                }
            } else {
                UI.showNotification('Erreur au démarrage du test', 'error');
            }
        } catch (error) {
            UI.showNotification('Erreur réseau', 'error');
        }
    },

    startManual: async (event, mode) => {
        event.preventDefault();
        
        const form = event.target;
        const targets = Array.from(form.querySelectorAll('input[name="targets"]:checked')).map(cb => cb.value);
        const tests = Array.from(form.querySelectorAll('input[name="test_types"]:checked')).map(cb => cb.value);
        
        if (targets.length === 0) {
            UI.showNotification('Sélectionnez au moins un disque', 'error');
            return;
        }
        
        if (tests.length === 0) {
            UI.showNotification('Sélectionnez au moins un test', 'error');
            return;
        }
        
        const duration = form.querySelector('[name="duration"]')?.value || 30;
        const size = form.querySelector('[name="size"]')?.value || '1G';
        
        const payload = {
            name: `${mode === 'zfs' ? 'ZFS' : 'Disk'}_${new Date().toLocaleString('fr-FR')}`,
            targets: targets,
            test_types: tests,
            is_zfs: mode === 'zfs',
            size: size,
            duration: parseInt(duration)
        };
        
        await Bench.start(payload);
    },

    runDailyNow: async () => {
        try {
            const response = await fetch('/get_config');
            const config = await response.json();
            
            if (!config.disks?.length) {
                UI.showNotification('Veuillez d\'abord configurer les disques dans DailyCheck', 'warning');
                return;
            }
            
            config.name = `DailyCheck_${new Date().toLocaleDateString('fr-FR')}`;
            await Bench.start(config);
        } catch (error) {
            UI.showNotification('Erreur lors du chargement de la configuration', 'error');
        }
    },

    startQuickSmart: async () => {
        const disks = Array.from(document.querySelectorAll('.disk-card strong')).map(s => s.innerText);
        if (disks.length === 0) {
            UI.showNotification('Aucun disque trouvé', 'error');
            return;
        }
        
        await Bench.start({
            name: `QuickSmart_${Date.now()}`,
            targets: disks,
            test_types: ['smart'],
            duration: 5
        });
    },

    saveDailyConfig: async () => {
        const taskId = Toolbox.addInstantTask('Sauvegarde configuration DailyCheck');
        try {
            const config = {
                disks: Array.from(document.querySelectorAll('.daily-disk:checked')).map(cb => cb.value),
                tests: Array.from(document.querySelectorAll('.daily-test:checked')).map(cb => cb.value),
                duration: parseInt(document.getElementById('dailyDuration')?.value) || 30,
                zfs_scrub: document.getElementById('check-zfs-scrub')?.checked || false,
                zfs_perf: document.getElementById('check-zfs-perf')?.checked || false
            };
            
            const response = await fetch('/save_config', {
                method: 'POST',
                headers: {'Content-Type': 'application/json'},
                body: JSON.stringify(config)
            });
            
            if (response.ok) {
                Toolbox.finishInstantTask(taskId, 'Finished', `${config.disks.length} disques, tests: ${config.tests.join(', ')}`);
                UI.showNotification('Configuration sauvegardée !', 'success');
            } else {
                Toolbox.finishInstantTask(taskId, 'Error', 'Erreur serveur');
                UI.showNotification('Erreur lors de la sauvegarde', 'error');
            }
        } catch (error) {
            Toolbox.finishInstantTask(taskId, 'Error', error.message);
            UI.showNotification('Erreur réseau', 'error');
        }
    },

    deleteTest: async (tid) => {
        if (!confirm('Supprimer ce rapport définitivement ?')) return;
        
        try {
            const response = await fetch(`/delete_test/${tid}`, { method: 'POST' });
            if (response.ok) {
                document.getElementById(`report-${tid}`)?.remove();
                UI.showNotification('Test supprimé', 'success');
                TestPanel.close();
                Charts.update(Charts.currentChartType);
            }
        } catch (error) {
            UI.showNotification('Erreur lors de la suppression', 'error');
        }
    }
};

// ============================================================
// TOOLBOX — Gestion des tâches avec historique et logs
// ============================================================
const Toolbox = {
    taskHistory: [],  // Historique persistant en mémoire

    // Ouvrir la toolbox (utilisé par toutes les actions)
    open: () => {
        const popup = document.getElementById('active-tasks');
        if (popup && !popup.classList.contains('show')) {
            popup.classList.add('show');
        }
        const btn = document.getElementById('task-status-btn');
        if (btn) {
            btn.classList.add('active');
            btn.innerHTML = '🔽 Tâches en cours';
        }
    },

    // Ajouter une tâche non-benchmark (sauvegarde, config, note…) et ouvrir la toolbox
    // Retourne l'id généré pour pouvoir appeler finishInstantTask ensuite
    addInstantTask: (name, detail = '') => {
        const id = `instant_${Date.now()}`;
        const now = Date.now();
        const task = {
            id, name, status: 'Running', progress: 0,
            current_op: detail, startTime: now, endTime: null, duration: null
        };
        Toolbox.taskHistory.unshift(task);
        Toolbox.log('INFO', id, `▶ ${name}${detail ? ' — ' + detail : ''}`);
        Toolbox.open();
        Toolbox.renderHistory();
        return id;
    },

    // Finaliser une tâche instantanée (status = 'Finished' | 'Error')
    finishInstantTask: (id, status = 'Finished', detail = '') => {
        const now = Date.now();
        const task = Toolbox.taskHistory.find(t => t.id === id);
        if (task) {
            task.status = status;
            task.progress = 100;
            task.endTime = now;
            task.duration = now - task.startTime;
            if (detail) task.current_op = detail;
            const emoji = status === 'Finished' ? '✅' : '❌';
            Toolbox.log(status === 'Finished' ? 'INFO' : 'ERROR', id,
                `${emoji} ${task.name} — ${Toolbox.formatDuration(task.duration)}${detail ? ' : ' + detail : ''}`);
        }
        Toolbox.renderHistory();
    },

    // Options de log (lues depuis les checkboxes — compatibles avec les deux panels)
    getLogOptions: () => {
        const g = (id1, id2, def) => {
            const el = document.getElementById(id1) || document.getElementById(id2);
            return el ? el.checked : def;
        };
        return {
            http:     g('tbx-http', 'log-http', true),
            commands: g('tbx-commands', 'log-commands', true),
            output:   g('tbx-output', 'log-output', true),
            duration: g('tbx-duration', 'log-duration', true),
            errors:   g('tbx-errors', 'log-errors', true),
            progress: g('tbx-progress', 'log-progress', false),
        };
    },

    // Formater une date ISO
    formatTime: (ts) => {
        if (!ts) return '—';
        return new Date(ts).toLocaleTimeString('fr-FR', {hour:'2-digit', minute:'2-digit', second:'2-digit'});
    },

    formatDuration: (ms) => {
        if (!ms || ms < 0) return '—';
        if (ms < 60000) return `${Math.round(ms/1000)}s`;
        return `${Math.floor(ms/60000)}m${Math.round((ms%60000)/1000)}s`;
    },

    // Logger une entrée (envoi au serveur + console)
    log: (level, taskId, message, extra = {}) => {
        const opts = Toolbox.getLogOptions();

        // Filtre selon les options
        if (level === 'HTTP' && !opts.http) return;
        if (level === 'CMD' && !opts.commands) return;
        if (level === 'OUT' && !opts.output) return;
        if (level === 'DEBUG' && !opts.progress) return;

        const entry = {
            ts: new Date().toISOString(),
            level,
            taskId,
            message,
            ...extra
        };

        // Format standard : [ISO8601] [LEVEL] [TASK_ID] message
        const line = `[${entry.ts}] [${level.padEnd(5)}] [${(taskId||'system').padEnd(20)}] ${message}`;
        console.log(line);

        // Envoi au serveur pour persistance
        fetch('/toolbox_log', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(entry)
        }).catch(() => {}); // Silencieux si endpoint pas encore dispo
    },

    // Gérer une mise à jour de progression
    handleProgressUpdate: (data) => {
        const now = Date.now();
        let task = Toolbox.taskHistory.find(t => t.id === data.id);

        if (!task) {
            task = {
                id: data.id,
                name: data.name || data.id,
                status: 'Running',
                progress: 0,
                current_op: '',
                startTime: now,
                endTime: null,
                duration: null,
                logs: []
            };
            Toolbox.taskHistory.unshift(task); // Ajouter en tête
            Toolbox.log('INFO', data.id, `Tâche démarrée: ${task.name}`);
            Toolbox.open();
        }

        const opts = Toolbox.getLogOptions();

        // Mise à jour du statut
        task.progress = data.progress || task.progress;
        task.current_op = data.current_op || task.current_op;

        if (opts.progress && data.current_op) {
            Toolbox.log('DEBUG', data.id, `[${data.progress}%] ${data.current_op}`);
        }

        if (data.status === 'Finished' || data.status === 'Error') {
            task.status = data.status;
            task.progress = 100;
            task.endTime = now;
            task.duration = now - task.startTime;

            const level = data.status === 'Finished' ? 'INFO' : 'ERROR';
            const msg = data.status === 'Finished'
                ? `Tâche terminée: ${task.name} (${Toolbox.formatDuration(task.duration)})`
                : `Tâche en erreur: ${task.name}`;
            Toolbox.log(level, data.id, msg);
            if (opts.duration) {
                Toolbox.log('INFO', data.id, `Durée: ${Toolbox.formatDuration(task.duration)}`);
            }
        }

        Toolbox.renderHistory();
    },

    // Supprimer une tâche de la toolbox
    removeTask: (taskId) => {
        Toolbox.taskHistory = Toolbox.taskHistory.filter(t => t.id !== taskId);
        Toolbox.log('INFO', taskId, 'Entrée supprimée de la toolbox');
        Toolbox.renderHistory();
    },

    // Vider l'historique (seulement les tâches terminées)
    clearHistory: () => {
        const running = Toolbox.taskHistory.filter(t => t.status === 'Running');
        Toolbox.taskHistory = running;
        Toolbox.log('INFO', 'system', 'Historique toolbox vidé');
        Toolbox.renderHistory();
    },

    // Afficher/masquer le panneau options logs
    toggleLogOptions: () => {
        const panel = document.getElementById('log-options-panel');
        if (panel) panel.classList.toggle('show');
    },

    // Rendu HTML de l'historique
    renderHistory: () => {
        const container = document.getElementById('tasks-container');
        if (!container) return;

        if (Toolbox.taskHistory.length === 0) {
            container.innerHTML = '<p class="text-muted" style="text-align:center; padding:20px;">Aucune tâche en cours</p>';
            document.getElementById('task-status-btn').classList.remove('active');
            return;
        }

        // Compter les tâches actives
        const runningCount = Toolbox.taskHistory.filter(t => t.status === 'Running').length;
        const btn = document.getElementById('task-status-btn');
        if (runningCount > 0) {
            btn.classList.add('active');
            btn.innerHTML = `🔽 ${runningCount} tâche(s) en cours`;
        } else {
            btn.classList.remove('active');
            btn.innerHTML = '🔽 Tâches en cours';
        }

        container.innerHTML = Toolbox.taskHistory.map(task => {
            const statusClass = task.status === 'Running' ? 'task-running'
                : task.status === 'Finished' ? 'task-success' : 'task-error';
            const statusEmoji = task.status === 'Running' ? '⏳'
                : task.status === 'Finished' ? '✅' : '❌';
            const statusLabel = task.status === 'Running' ? 'En cours'
                : task.status === 'Finished' ? 'Terminé' : 'Erreur';
            const badgeClass = task.status === 'Running' ? 'running'
                : task.status === 'Finished' ? 'success' : 'error';

            const startStr = Toolbox.formatTime(task.startTime);
            const endStr = task.endTime ? Toolbox.formatTime(task.endTime) : '—';
            const durStr = task.duration ? Toolbox.formatDuration(task.duration) : '—';

            const progressBar = task.status === 'Running' ? `
                <div class="progress-bar-bg" style="margin-top:6px;">
                    <div class="progress-bar-fill" style="width: ${task.progress}%"></div>
                </div>` : '';

            const currentOp = task.current_op && task.status === 'Running'
                ? `<div class="task-current-op">↳ ${task.current_op}</div>` : '';

            return `
                <div class="task-progress-item ${statusClass}" id="task-${task.id}">
                    <div class="task-header">
                        <span class="task-name">${statusEmoji} ${task.name}</span>
                        <div class="task-actions">
                            <span class="task-status-badge ${badgeClass}">${statusLabel}</span>
                            <button class="task-remove-btn" onclick="Toolbox.removeTask('${task.id}')" title="Supprimer">✕</button>
                        </div>
                    </div>
                    <div class="task-meta">
                        <span>🕐 ${startStr}</span>
                        ${task.endTime ? `<span>→ ${endStr}</span>` : ''}
                        ${task.duration ? `<span>⏱️ ${durStr}</span>` : ''}
                        ${task.status === 'Running' ? `<span>${task.progress}%</span>` : ''}
                    </div>
                    ${currentOp}
                    ${progressBar}
                </div>
            `;
        }).join('');
    }
};


// Gestion des graphiques
const Charts = {
    currentChartType: 'read',

    init: () => {
        // Rendre les graphiques cliquables
        document.addEventListener('click', (e) => {
            if (e.target.closest('.point')) {
                const point = e.target.closest('.point');
                const testId = point.getAttribute('data-test-id');
                if (testId) TestPanel.open(testId);
            }
        });
    },

update: async (type = null) => {
    if (type) Charts.currentChartType = type;
    const currentType = Charts.currentChartType;

    // Mettre en évidence le bouton de type actif
    document.querySelectorAll('.chart-type-btn').forEach(btn => {
        btn.classList.toggle('btn-active-type', btn.dataset.type === currentType);
    });

    const selected = Array.from(document.querySelectorAll('.chart-toggle:checked')).map(cb => cb.value);
    const container = document.getElementById('chart-container');
    
    if (selected.length === 0) {
        container.innerHTML = '<p style="padding:40px; text-align:center; color:#7f8c8d;">📊 Cochez des tests dans l\'historique pour afficher les graphiques</p>';
        return;
    }
    
    container.innerHTML = '<p style="padding:30px; text-align:center; color:#7f8c8d;">⏳ Chargement…</p>';

    try {
        const params = new URLSearchParams({ type: currentType });
        selected.forEach(id => params.append('ids', id));
        
        Toolbox.log('HTTP', 'charts', `GET /get_charts?type=${currentType}&ids=${selected.join(',')}`);

        const response = await fetch(`/get_charts?${params.toString()}`);
        const html = await response.text();
        
        container.innerHTML = html;
        
        // Ajuster tous les SVG injectés
        container.querySelectorAll('svg').forEach(svgEl => {
            svgEl.style.width = '100%';
            svgEl.style.height = 'auto';
            svgEl.removeAttribute('width');
        });
        
        // Rebrancher les tooltips JS sur les points cliquables
        Charts.bindPointTooltips(container);
        
    } catch (error) {
        console.error('Erreur graphique:', error);
        container.innerHTML = `<p style="color:#e74c3c; padding:20px;">❌ Erreur chargement graphique</p>`;
    }
},

// Créer un tooltip flottant JS pour les points SVG
bindPointTooltips: (container) => {
    let tip = document.getElementById('svg-chart-tooltip');
    if (!tip) {
        tip = document.createElement('div');
        tip.id = 'svg-chart-tooltip';
        tip.style.cssText = `
            position: fixed; z-index: 20000; background: #2c3e50; color: white;
            padding: 8px 12px; border-radius: 6px; font-size: 0.82em; line-height: 1.6;
            pointer-events: none; opacity: 0; transition: opacity 0.15s;
            white-space: pre-line; max-width: 300px; box-shadow: 0 4px 14px rgba(0,0,0,0.35);
        `;
        document.body.appendChild(tip);
    }

    const points = container.querySelectorAll('[data-test-id], circle[data-tooltip], circle[title]');
    points.forEach(point => {
        if (point._tooltipBound) return;
        point._tooltipBound = true;
        point.style.cursor = 'pointer';

        point.addEventListener('mouseenter', () => {
            const text = point.getAttribute('data-tooltip') || point.getAttribute('title') || '';
            if (!text) return;
            tip.textContent = text.replace(/&quot;/g, '"').replace(/&amp;/g, '&');
            tip.style.opacity = '1';
        });

        point.addEventListener('mousemove', (e) => {
            const x = e.clientX + 16;
            const y = e.clientY - 10;
            const maxX = window.innerWidth - tip.offsetWidth - 10;
            tip.style.left = Math.min(x, maxX) + 'px';
            tip.style.top = y + 'px';
        });

        point.addEventListener('mouseleave', () => { tip.style.opacity = '0'; });

        point.addEventListener('click', (e) => {
            e.stopPropagation();
            const testId = point.getAttribute('data-test-id');
            if (testId) TestPanel.open(testId);
        });
    });
},

// Correction du bouton SmartOnly
filterSmartOnly: () => {
    document.querySelectorAll('.chart-toggle').forEach(cb => {
        const card = cb.closest('.report-card');
        const name = card?.querySelector('strong')?.textContent || '';
        cb.checked = name.toLowerCase().includes('smart') || name.toLowerCase().includes('quick');
    });
    // Basculer vers le type errors si on filtre SMART
    Charts.update('errors');
},

    // FONCTIONS D'AFFICHAGE PAR TYPE
    showRead: () => Charts.update('read'),
    showLatency: () => Charts.update('latency'),
    showErrors: () => Charts.update('errors'),

    toggleDaily: () => {
        const dailyChecks = document.querySelectorAll('.reports-grid .report-card');
        let anyChecked = false;
        
        dailyChecks.forEach(card => {
            if (card.textContent.includes('Daily')) {
                const cb = card.querySelector('.chart-toggle');
                if (cb && cb.checked) anyChecked = true;
            }
        });
        
        dailyChecks.forEach(card => {
            if (card.textContent.includes('Daily')) {
                const cb = card.querySelector('.chart-toggle');
                if (cb) cb.checked = !anyChecked;
            }
        });
        
        Charts.update(Charts.currentChartType);
    },

    selectDaily: (selectAll) => {
        document.querySelectorAll('.reports-grid .chart-toggle').forEach(cb => {
            const isDaily = cb.closest('.report-card')?.textContent.includes('Daily');
            if (isDaily) {
                cb.checked = selectAll;
            }
        });
        Charts.update(Charts.currentChartType);
    }
};


// Socket.IO events
socket.on('connect', () => {
    console.log('Connecté au serveur');
});

socket.on('backup_progress', (data) => {
    const pct = data.percent ?? 0;
    const bar = document.getElementById('backup-progress-bar');
    const statusEl = document.getElementById('backup-status');
    if (bar) bar.style.width = `${pct}%`;
    if (statusEl) {
        statusEl.innerHTML = `
            <span style="font-weight:600;">${pct}%</span>
            — ${data.copied || '?'} / ${data.total || '?'}
            <span style="color:#7f8c8d; margin-left:8px;">⚡ ${data.speed || '—'}</span>
            <span style="color:#7f8c8d; margin-left:8px;">⏱️ ${data.elapsed || '?'}s</span>
        `;
    }
    // Afficher la section progression si masquée
    const progressSection = document.querySelector('#backup-modal #backup-progress');
    if (progressSection) progressSection.style.display = 'block';

    // Mettre à jour la tâche dans la toolbox
    if (Backup._taskId) {
        const task = Toolbox.taskHistory.find(t => t.id === Backup._taskId);
        if (task) {
            task.progress = pct;
            task.current_op = `${data.copied || '?'} / ${data.total || '?'} @ ${data.speed || '—'}`;
            Toolbox.renderHistory();
        }
    }
});

socket.on('backup_complete', (data) => {
    if (data.status === 'success') {
        UI.showNotification(data.message, 'success');
        const bar = document.getElementById('backup-progress-bar');
        const statusEl = document.getElementById('backup-status');
        if (bar) bar.style.width = '100%';
        if (statusEl) statusEl.textContent = '✅ ' + data.message;
        setTimeout(() => Backup.closeModal(), 3000);
    } else {
        UI.showNotification('❌ ' + (data.message || 'Erreur lors de la sauvegarde'), 'error');
        const statusEl = document.getElementById('backup-status');
        if (statusEl) statusEl.textContent = '❌ ' + data.message;
    }
    // Finaliser la tâche toolbox
    if (Backup._taskId) {
        Toolbox.finishInstantTask(
            Backup._taskId,
            data.status === 'success' ? 'Finished' : 'Error',
            data.message || ''
        );
        Backup._taskId = null;
    }
});

socket.on('sys_stats', (stats) => {
    document.getElementById('stat-users').innerText = stats.users;
    document.getElementById('stat-io').innerText = stats.io;
});
socket.on('progress_update', (data) => {
    Toolbox.handleProgressUpdate(data);
    
    // Mettre à jour la carte report dans la liste
    ReportsList.updateCard(data.id, data.status, data.progress);

    // Mettre à jour les icônes de santé + le panel si ouvert sur ce test
    if (data.status === 'Finished') {
        if (data.data) {
            Object.keys(data.data).forEach(diskName => {
                const cleanName = diskName.replace('/dev/', '');
                const healthIcon = document.getElementById(`health-${cleanName}`);
                if (healthIcon && data.data[diskName].smart) {
                    const hasErrors = data.data[diskName].smart.critical_alerts?.length > 0;
                    healthIcon.innerText = hasErrors ? '🔴' : '🟢';
                }
            });
        }
        // Rafraîchir le panel s'il affiche ce test
        if (TestPanel._currentId === data.id) {
            setTimeout(() => TestPanel.open(data.id), 800);
        }
    }
});

// Réception des logs de commandes backend (fio, smartctl, zpool...)
socket.on('toolbox_log', (entry) => {
    const opts = Toolbox.getLogOptions();
    const level = entry.level || 'INFO';
    // Filtrer selon les options
    if (level === 'CMD' && !opts.commands) return;
    if (level === 'OUT' && !opts.output) return;
    if (level === 'HTTP' && !opts.http) return;
    if (level === 'DEBUG' && !opts.progress) return;

    // Ajouter à l'historique en mémoire (limité à 500)
    Toolbox.logEntries = Toolbox.logEntries || [];
    Toolbox.logEntries.push({
        ts: entry.ts || new Date().toISOString(),
        level,
        taskId: entry.taskId || 'system',
        message: entry.message || ''
    });
    if (Toolbox.logEntries.length > 500) Toolbox.logEntries.shift();

    // Persister côté serveur
    fetch('/toolbox_log', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify(entry)
    }).catch(() => {});
});

// Initialisation
document.addEventListener('DOMContentLoaded', () => {
    Navigation.init();
    Charts.init();
    
    // Les report-cards ont maintenant onclick=TestPanel.open() dans le HTML
    // (plus de navigation)
    
    // Rafraîchir la liste des tâches actives toutes les 5 secondes
    setInterval(async () => {
        try {
            const response = await fetch('/get_active_tasks');
            const tasks = await response.json();
            UI.updateActiveTasks(tasks);
        } catch (error) {
            console.error('Erreur mise à jour tâches:', error);
        }
    }, 2000);
});

document.querySelectorAll('.disk-card').forEach(card => {
    card.addEventListener('click', (e) => {
        // Ne pas ouvrir si on clique sur l'icône note
        if (e.target.closest('.note-icon')) return;
        
        const diskName = card.getAttribute('data-disk');

        // Si on clique sur l'expand-icon : toggle (déploie OU replie)
        if (e.target.closest('.expand-icon')) {
            e.stopPropagation();
            UI.toggleDiskExpand(card, diskName);
            return;
        }
        
        // Clic sur le reste de la carte : déploie uniquement (ne replie pas)
        if (!card.classList.contains('expanded')) {
            UI.toggleDiskExpand(card, diskName);
        }
        // Si déjà expanded et clic sur la carte (pas l'icon) : on ne replie pas
    });
    
    // Ajouter l'icône d'expansion si elle n'existe pas déjà (fallback)
    if (!card.querySelector('.expand-icon')) {
        const expandIcon = document.createElement('span');
        expandIcon.className = 'expand-icon';
        expandIcon.innerHTML = '🔽';
        expandIcon.title = 'Déplier / Replier';
        card.insertBefore(expandIcon, card.firstChild);
    }
});

// Styles animations
const style = document.createElement('style');
style.textContent = `
    @keyframes slideIn {
        from { transform: translateX(100%); opacity: 0; }
        to { transform: translateX(0); opacity: 1; }
    }
    
    @keyframes slideOut {
        from { transform: translateX(0); opacity: 1; }
        to { transform: translateX(100%); opacity: 0; }
    }
    
    .task-progress-item {
        padding: 10px;
        margin: 10px 0;
        background: #f8f9fa;
        border-radius: 5px;
        transition: opacity 0.3s ease;
    }
    
    .task-info {
        display: flex;
        justify-content: space-between;
        margin-bottom: 5px;
        font-size: 0.9em;
    }
    
    .task-progress {
        font-weight: bold;
        color: #3498db;
    }
    
    .point:hover {
        stroke: #e74c3c;
        stroke-width: 3;
    }
    
    .notification {
        box-shadow: 0 4px 15px rgba(0,0,0,0.2);
        font-weight: 500;
    }
    
    .modal-header, .modal-footer {
        display: flex;
        justify-content: space-between;
        align-items: center;
    }
    
    .close-btn {
        background: none;
        border: none;
        font-size: 24px;
        cursor: pointer;
        color: #7f8c8d;
    }
    
    .close-btn:hover {
        color: #e74c3c;
    }
`;
document.head.appendChild(style);


// ══ NAVIGATION + MODES ══
// ═══════════════════════════════════════════════════════════════
// NAVIGATION — slider 4 modes
// ═══════════════════════════════════════════════════════════════
const NAV_LABELS = ['📊 Monitoring', '💾 Backup', '⚖️ Parité', '📋 Logs'];
let _currentSlide = 0;
let _isMobile = () => window.innerWidth <= 768;

const Navigation = {
    init: () => {
        Navigation._updateArrows();
        Navigation._updateDots();
        Navigation._updateTabs();
        // Restaurer depuis sessionStorage
        const saved = parseInt(sessionStorage.getItem('activeSlide') || '0');
        if (saved > 0) Navigation.go(saved, true);
    },

    go: (index, instant = false) => {
        _currentSlide = Math.max(0, Math.min(3, index));
        sessionStorage.setItem('activeSlide', _currentSlide);

        const container = document.getElementById('slides-container');
        if (!container) return;

        if (_isMobile()) {
            // Mobile : translation verticale — chaque slide fait 100vh
            // On utilise le viewport pour un scroll propre
            const slideH = window.innerHeight;
            container.style.transition = instant ? 'none' : 'transform 0.42s cubic-bezier(0.4,0,0.2,1)';
            container.style.transform = `translateY(-${_currentSlide * slideH}px)`;
        } else {
            // Desktop : translation horizontale
            container.style.transition = instant ? 'none' : 'transform 0.42s cubic-bezier(0.4,0,0.2,1)';
            container.style.transform = `translateX(-${_currentSlide * 25}%)`;
        }

        Navigation._updateTabs();
        Navigation._updateDots();
        Navigation._updateArrows();
        Navigation._updateModeLabel();

        // Sur slide Logs : charger les logs
        if (_currentSlide === 3) {
            setTimeout(() => LogViewer.loadFromServer(), 200);
        }
    },

    next: () => Navigation.go(_currentSlide + 1),
    prev: () => Navigation.go(_currentSlide - 1),

    toggleDrawer: () => {
        const drawer = document.getElementById('nav-drawer');
        const overlay = document.getElementById('drawer-overlay');
        const hamburger = document.getElementById('hamburger');
        drawer.classList.toggle('open');
        overlay.classList.toggle('show');
        hamburger.classList.toggle('open');
    },

    closeDrawer: () => {
        document.getElementById('nav-drawer')?.classList.remove('open');
        document.getElementById('drawer-overlay')?.classList.remove('show');
        document.getElementById('hamburger')?.classList.remove('open');
    },

    _updateTabs: () => {
        document.querySelectorAll('.nav-tab, .drawer-item').forEach(btn => {
            btn.classList.toggle('active', parseInt(btn.dataset.mode) === _currentSlide);
        });
    },

    _updateDots: () => {
        document.querySelectorAll('.slide-dot').forEach((dot, i) => {
            dot.classList.toggle('active', i === _currentSlide);
        });
    },

    _updateArrows: () => {
        const prev = document.getElementById('nav-prev');
        const next = document.getElementById('nav-next');
        if (prev) prev.disabled = _currentSlide === 0;
        if (next) next.disabled = _currentSlide === 3;
    },

    _updateModeLabel: () => {
        const el = document.getElementById('nav-mode-label');
        if (el) el.textContent = NAV_LABELS[_currentSlide];
    }
};

// Recalcul au resize (passage desktop ↔ mobile)
window.addEventListener('resize', () => {
    Navigation.go(_currentSlide, true);
});

// Swipe tactile horizontal (desktop) et vertical (mobile)
(function() {
    let sx = 0, sy = 0;
    const vp = document.getElementById('slides-viewport');
    if (!vp) return;
    vp.addEventListener('touchstart', e => {
        sx = e.touches[0].clientX;
        sy = e.touches[0].clientY;
    }, {passive: true});
    vp.addEventListener('touchend', e => {
        const dx = e.changedTouches[0].clientX - sx;
        const dy = e.changedTouches[0].clientY - sy;
        if (_isMobile()) {
            if (Math.abs(dy) > 50 && Math.abs(dy) > Math.abs(dx)) {
                dy < 0 ? Navigation.next() : Navigation.prev();
            }
        } else {
            if (Math.abs(dx) > 60 && Math.abs(dx) > Math.abs(dy)) {
                dx < 0 ? Navigation.next() : Navigation.prev();
            }
        }
    }, {passive: true});
})();

// ═══════════════════════════════════════════════════════════════
// PARITE — scrub ZFS + SMART self-test + intégrité
// ═══════════════════════════════════════════════════════════════
const Parite = {
    startScrub: async (pool) => {
        const tid = Toolbox.addInstantTask(`Scrub ZFS ${pool}`);
        const prog = document.getElementById(`scrub-progress-${pool}`);
        const bar = document.getElementById(`scrub-bar-${pool}`);
        const status = document.getElementById(`scrub-status-${pool}`);
        if (prog) prog.style.display = 'block';
        try {
            const res = await fetch('/zfs_scrub', {
                method: 'POST',
                headers: {'Content-Type':'application/json'},
                body: JSON.stringify({pool})
            });
            if (res.ok) {
                Toolbox.finishInstantTask(tid, 'Finished', `Scrub lancé sur ${pool}`);
                if (status) status.textContent = '✅ Scrub lancé — vérifiez le statut dans quelques minutes';
                if (bar) bar.style.width = '100%';
                UI.showNotification(`Scrub lancé sur ${pool}`, 'success');
            } else {
                throw new Error(await res.text());
            }
        } catch(e) {
            Toolbox.finishInstantTask(tid, 'Error', e.message);
            if (status) status.textContent = '❌ ' + e.message;
            UI.showNotification('Erreur scrub: ' + e.message, 'error');
        }
    },

    stopScrub: async (pool) => {
        try {
            await fetch('/zfs_scrub_stop', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({pool})});
            UI.showNotification(`Scrub arrêté sur ${pool}`, 'info');
        } catch(e) { UI.showNotification('Erreur: ' + e.message, 'error'); }
    },

    checkStatus: async (pool) => {
        try {
            const res = await fetch(`/zfs_status/${pool}`);
            const data = await res.json();
            const el = document.getElementById(`scrub-status-${pool}`);
            const prog = document.getElementById(`scrub-progress-${pool}`);
            if (prog) prog.style.display = 'block';
            if (el) el.textContent = data.status || 'Statut récupéré';
        } catch(e) { UI.showNotification('Erreur: ' + e.message, 'error'); }
    },

    clearErrors: async (pool) => {
        if (!confirm(`Effacer les compteurs d'erreurs de ${pool} ?`)) return;
        try {
            await fetch('/zfs_clear', {method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify({pool})});
            UI.showNotification(`Erreurs effacées pour ${pool}`, 'success');
        } catch(e) { UI.showNotification('Erreur: ' + e.message, 'error'); }
    },

    smartTest: async (disk, type) => {
        const el = document.getElementById(`smart-test-${disk}`);
        if (type === 'status') {
            try {
                const res = await fetch(`/smart_status/${disk}`);
                const data = await res.json();
                if (el) el.innerHTML = `<pre style="white-space:pre-wrap;font-size:0.8em;color:#555;">${data.output || 'Aucun résultat'}</pre>`;
            } catch(e) { if (el) el.textContent = 'Erreur: ' + e.message; }
            return;
        }
        const tid = Toolbox.addInstantTask(`SMART ${type === 'short' ? 'court' : 'long'} — ${disk}`);
        if (el) el.textContent = '⏳ Test en cours…';
        try {
            const res = await fetch('/smart_test', {
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body: JSON.stringify({disk, type})
            });
            const data = await res.json();
            Toolbox.finishInstantTask(tid, 'Finished', `Test SMART ${type} lancé`);
            if (el) el.innerHTML = `<span style="color:var(--success)">✅ ${data.message || 'Test lancé'}</span>`;
            UI.showNotification(`Test SMART ${type} lancé sur ${disk}`, 'success');
        } catch(e) {
            Toolbox.finishInstantTask(tid, 'Error', e.message);
            if (el) el.innerHTML = `<span style="color:var(--danger)">❌ ${e.message}</span>`;
        }
    },

    checkIntegrity: async () => {
        const path = document.getElementById('integrity-path')?.value;
        const algo = document.getElementById('integrity-algo')?.value || 'sha256';
        const expected = document.getElementById('integrity-expected')?.value || '';
        const result = document.getElementById('integrity-result');
        if (!path) { UI.showNotification('Entrez un chemin', 'error'); return; }
        if (result) result.textContent = '⏳ Calcul en cours…';
        const tid = Toolbox.addInstantTask(`Intégrité ${algo}`, path);
        try {
            const res = await fetch('/check_integrity', {
                method:'POST',
                headers:{'Content-Type':'application/json'},
                body: JSON.stringify({path, algo, expected})
            });
            const data = await res.json();
            Toolbox.finishInstantTask(tid, data.match !== false ? 'Finished' : 'Error', data.hash || '');
            if (result) {
                let out = `Algorithme : ${algo.toUpperCase()}\nFichier    : ${path}\nChecksum   : ${data.hash || '?'}`;
                if (expected) out += `\nAttendu    : ${expected}\nRésultat   : ${data.match ? '✅ IDENTIQUE' : '❌ DIFFÉRENT'}`;
                result.textContent = out;
                result.style.color = expected ? (data.match ? '#2ecc71' : '#e74c3c') : '#cdd3de';
            }
        } catch(e) {
            Toolbox.finishInstantTask(tid, 'Error', e.message);
            if (result) result.textContent = '❌ Erreur : ' + e.message;
        }
    }
};

// ═══════════════════════════════════════════════════════════════
// BACKUP étendu — formulaire slide-1
// ═══════════════════════════════════════════════════════════════
Backup.startFromForm = async (event) => {
    event.preventDefault();
    const src = document.getElementById('backup-src-select').value;
    const dest = document.getElementById('backup-dest-main').value;
    const bs = document.getElementById('backup-bs-main').value;
    let conv = [];
    if (document.getElementById('bk-noerror').checked) conv.push('noerror');
    if (document.getElementById('bk-sync').checked) conv.push('sync');

    const payload = { source: src, destination: dest, bs, conv: conv.join(','), status: 'progress' };

    const prog = document.getElementById('backup-progress-main');
    const btn = document.getElementById('bk-btn-main');
    if (prog) prog.style.display = 'block';
    if (btn) { btn.disabled = true; btn.textContent = '⏳ En cours…'; }

    try {
        const res = await fetch('/start_backup', {
            method:'POST', headers:{'Content-Type':'application/json'},
            body: JSON.stringify(payload)
        });
        if (res.ok) {
            Backup._taskId = Toolbox.addInstantTask(`Sauvegarde ${src}`, `→ ${dest}`);
            UI.showNotification('Sauvegarde démarrée', 'success');
            BackupHistory.add(src, dest, 'running');
        } else {
            UI.showNotification('Erreur au démarrage', 'error');
            if (btn) { btn.disabled = false; btn.textContent = '🚀 Démarrer la sauvegarde'; }
        }
    } catch(e) {
        UI.showNotification('Erreur réseau', 'error');
        if (btn) { btn.disabled = false; btn.textContent = '🚀 Démarrer la sauvegarde'; }
    }
};

Backup.startRestore = async (event) => {
    event.preventDefault();
    const src = document.getElementById('restore-src').value;
    const dest = document.getElementById('restore-dest').value;
    if (!confirm(`⚠️ Restaurer ${src} vers ${dest} ?\nToutes les données de ${dest} seront ÉCRASÉES.`)) return;
    const payload = { source: src, destination: dest, bs: '4M', conv: 'noerror,sync', status: 'progress', reverse: true };
    const prog = document.getElementById('restore-progress');
    if (prog) prog.style.display = 'block';
    try {
        const res = await fetch('/start_backup', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
        if (res.ok) {
            Backup._taskId = Toolbox.addInstantTask(`Restauration ${dest}`, `← ${src}`);
            UI.showNotification('Restauration démarrée', 'success');
        } else { UI.showNotification('Erreur au démarrage', 'error'); }
    } catch(e) { UI.showNotification('Erreur réseau', 'error'); }
};

// Mise à jour barres de progression slide-1
socket.on('backup_progress', (data) => {
    const pct = data.percent ?? 0;
    // Barre slide-1
    ['bk-bar-main', 'restore-bar'].forEach(id => {
        const bar = document.getElementById(id);
        if (bar) bar.style.width = `${pct}%`;
    });
    const pctLabel = document.getElementById('bk-pct-label');
    if (pctLabel) pctLabel.textContent = pct + '%';
    const statusMain = document.getElementById('bk-status-main');
    if (statusMain) {
        statusMain.textContent = `${data.copied || '?'} / ${data.total || '?'} @ ${data.speed || '—'}`;
    }
    const restoreStatus = document.getElementById('restore-status');
    if (restoreStatus) restoreStatus.textContent = statusMain?.textContent || '';
    // Toolbox
    if (Backup._taskId) {
        const task = Toolbox.taskHistory.find(t => t.id === Backup._taskId);
        if (task) { task.progress = pct; task.current_op = `${data.copied || '?'} / ${data.total || '?'} @ ${data.speed || '—'}`; Toolbox.renderHistory(); }
    }
});

socket.on('backup_complete', (data) => {
    const btn = document.getElementById('bk-btn-main');
    if (btn) { btn.disabled = false; btn.textContent = '🚀 Démarrer la sauvegarde'; }
    if (data.status === 'success') {
        UI.showNotification(data.message, 'success');
        document.querySelectorAll('#bk-bar-main, #restore-bar').forEach(b => b.style.width = '100%');
        BackupHistory.finish(data.status);
    } else {
        UI.showNotification('❌ ' + (data.message || 'Erreur'), 'error');
        BackupHistory.finish('error');
    }
    if (Backup._taskId) {
        Toolbox.finishInstantTask(Backup._taskId, data.status === 'success' ? 'Finished' : 'Error', data.message || '');
        Backup._taskId = null;
    }
});

// Historique simple des sauvegardes (en mémoire)
const BackupHistory = {
    entries: [],
    _current: null,
    add: (src, dest, status) => {
        const e = { src, dest, status, ts: new Date().toLocaleString('fr-FR'), end: null };
        BackupHistory._current = e;
        BackupHistory.entries.unshift(e);
        BackupHistory.render();
    },
    finish: (status) => {
        if (BackupHistory._current) {
            BackupHistory._current.status = status;
            BackupHistory._current.end = new Date().toLocaleString('fr-FR');
        }
        BackupHistory.render();
    },
    render: () => {
        const el = document.getElementById('backup-history-list');
        if (!el) return;
        if (!BackupHistory.entries.length) {
            el.innerHTML = '<p class="text-muted" style="text-align:center;padding:20px;">Aucune sauvegarde effectuée</p>';
            return;
        }
        el.innerHTML = BackupHistory.entries.map(e => `
            <div class="backup-entry ${e.status}">
                <div class="backup-entry-info">
                    <div class="backup-entry-name">${e.status === 'success' ? '✅' : e.status === 'error' ? '❌' : '⏳'} ${e.src.replace('/dev/','')} → ${e.dest}</div>
                    <div class="backup-entry-meta">Démarré ${e.ts}${e.end ? ' · Terminé ' + e.end : ''}</div>
                </div>
            </div>
        `).join('');
    }
};

// ═══════════════════════════════════════════════════════════════
// LOG VIEWER — slide 3
// ═══════════════════════════════════════════════════════════════
const LogViewer = {
    entries: [],
    autoScroll: true,

    loadFromServer: async () => {
        try {
            const res = await fetch('/get_logs');
            if (!res.ok) return;
            const data = await res.json();
            LogViewer.entries = data.entries || [];
            LogViewer.filter();
        } catch(e) { console.warn('Logs non disponibles', e); }
    },

    push: (entry) => {
        LogViewer.entries.push(entry);
        if (LogViewer.entries.length > 2000) LogViewer.entries.shift();
        LogViewer.filter();
    },

    filter: () => {
        const search = document.getElementById('log-search')?.value?.toLowerCase() || '';
        const taskF = document.getElementById('log-task-filter')?.value?.toLowerCase() || '';
        const levels = {
            INFO:  document.getElementById('lf-info')?.checked  ?? true,
            ERROR: document.getElementById('lf-error')?.checked ?? true,
            WARN:  document.getElementById('lf-warn')?.checked  ?? true,
            CMD:   document.getElementById('lf-cmd')?.checked   ?? true,
            OUT:   document.getElementById('lf-out')?.checked   ?? false,
            HTTP:  document.getElementById('lf-http')?.checked  ?? false,
            DEBUG: document.getElementById('lf-debug')?.checked ?? false,
        };

        const filtered = LogViewer.entries.filter(e => {
            const lvl = (e.level || 'INFO').toUpperCase();
            if (!levels[lvl]) return false;
            if (search && !e.message?.toLowerCase().includes(search)) return false;
            if (taskF && !(e.taskId || '').toLowerCase().includes(taskF)) return false;
            return true;
        });

        LogViewer.render(filtered);
        const badge = document.getElementById('log-count-badge');
        if (badge) badge.textContent = `${filtered.length} entrée${filtered.length > 1 ? 's' : ''}`;
    },

    render: (entries) => {
        const el = document.getElementById('log-viewer-main');
        if (!el) return;
        if (!entries || !entries.length) {
            el.innerHTML = '<div class="log-empty"><span class="log-empty-icon">📋</span><span>Aucun log ne correspond aux filtres</span></div>';
            return;
        }
        el.innerHTML = entries.map(e => {
            const ts = e.ts ? e.ts.replace('T', ' ').substring(0, 19) : '—';
            const lvl = (e.level || 'INFO').toUpperCase();
            const taskId = (e.taskId || 'system').substring(0, 18);
            const msg = (e.message || '').replace(/</g,'&lt;').replace(/>/g,'&gt;');
            return `<div class="log-line"><span class="log-ts">${ts}</span><span class="log-level ${lvl}">${lvl}</span><span class="log-task">${taskId}</span><span class="log-msg">${msg}</span></div>`;
        }).join('');
        if (LogViewer.autoScroll) el.scrollTop = el.scrollHeight;
    },

    scrollBottom: () => {
        const el = document.getElementById('log-viewer-main');
        if (el) el.scrollTop = el.scrollHeight;
    },

    clear: () => {
        LogViewer.entries = [];
        LogViewer.filter();
    },

    export: () => {
        const lines = LogViewer.entries.map(e =>
            `[${e.ts || ''}] [${(e.level||'INFO').padEnd(5)}] [${(e.taskId||'system').padEnd(20)}] ${e.message || ''}`
        ).join('\n');
        const blob = new Blob([lines], {type:'text/plain'});
        const a = document.createElement('a');
        a.href = URL.createObjectURL(blob);
        a.download = `storage-monitor-${new Date().toISOString().slice(0,10)}.log`;
        a.click();
        URL.revokeObjectURL(a.href);
    }
};

// Alimenter le log viewer depuis les events toolbox
socket.on('toolbox_log', (entry) => {
    LogViewer.push(entry);
    // Aussi dans la toolbox (comportement existant)
    const opts = Toolbox.getLogOptions();
    const level = entry.level || 'INFO';
    if (level === 'CMD' && !opts.commands) return;
    if (level === 'OUT' && !opts.output) return;
    if (level === 'HTTP' && !opts.http) return;
    if (level === 'DEBUG' && !opts.progress) return;
    Toolbox.logEntries = Toolbox.logEntries || [];
    Toolbox.logEntries.push({ ts: entry.ts || new Date().toISOString(), level, taskId: entry.taskId || 'system', message: entry.message || '' });
    if (Toolbox.logEntries.length > 500) Toolbox.logEntries.shift();
    fetch('/toolbox_log', { method:'POST', headers:{'Content-Type':'application/json'}, body: JSON.stringify(entry) }).catch(()=>{});
});

// Miroir tasks-container dans slide-3 logs
const _origRenderHistory = Toolbox.renderHistory.bind(Toolbox);
Toolbox.renderHistory = () => {
    _origRenderHistory();
    const logsContainer = document.getElementById('tasks-container-logs');
    if (logsContainer) {
        const main = document.getElementById('tasks-container');
        if (main) logsContainer.innerHTML = main.innerHTML;
    }
};



// ═══════════════════════════════════════════════════════════════
// TEST PANEL — panneau latéral pour les détails d'un test
// ═══════════════════════════════════════════════════════════════
const TestPanel = {
    _currentId: null,

    open: async (testId) => {
        TestPanel._currentId = testId;
        const panel  = document.getElementById('test-panel');
        const overlay = document.getElementById('test-panel-overlay');
        const body   = document.getElementById('test-panel-body');

        // Ouvrir immédiatement avec spinner
        body.innerHTML = '<div class="test-panel-loading"><div class="test-panel-spinner"></div><span>Chargement…</span></div>';
        panel.classList.add('open');
        overlay.classList.add('show');
        document.body.style.overflow = 'hidden';

        // Lire les métadonnées depuis la carte existante dans le DOM (0 fetch)
        const card = document.getElementById(`report-${testId}`);
        if (card) {
            const name   = card.querySelector('strong')?.textContent || testId;
            const date   = card.querySelector('.date')?.textContent || '';
            const badge  = card.querySelector('.badge');
            const status = badge?.textContent?.trim() || '?';
            document.getElementById('test-panel-name').textContent = name;
            document.getElementById('test-panel-meta').innerHTML =
                `📅 ${date} &nbsp;·&nbsp; <span class="test-panel-status ${status.toLowerCase()}">${status}</span>`;
            const icons = { Finished:'✅', Running:'⏳', Error:'❌' };
            document.getElementById('test-panel-icon').textContent = icons[status] || '📊';
        }

        try {
            const res = await fetch(`/test_fragment/${testId}`);
            if (!res.ok) throw new Error(`Erreur serveur ${res.status}`);
            const html = await res.text();

            // Le fragment contient ses propres <style> + contenu — on l'injecte directement
            body.innerHTML = html;
            body.scrollTop = 0;

        } catch (err) {
            body.innerHTML = `
                <div style="padding:40px; text-align:center;">
                    <div style="font-size:2.5em; margin-bottom:12px;">❌</div>
                    <p style="color:#e74c3c; font-weight:600;">Impossible de charger le rapport</p>
                    <small style="color:#7f8c8d;">${err.message}</small>
                    <div style="margin-top:20px;">
                        <a href="/test_detail/${testId}" target="_blank"
                           style="display:inline-block; padding:8px 18px; background:var(--primary); color:#fff;
                                  border-radius:6px; text-decoration:none; font-weight:600;">
                            ↗ Ouvrir dans un onglet
                        </a>
                    </div>
                </div>`;
        }
    },

    close: () => {
        TestPanel._currentId = null;
        document.getElementById('test-panel')?.classList.remove('open');
        document.getElementById('test-panel-overlay')?.classList.remove('show');
        document.body.style.overflow = '';
    },

    openExternal: () => {
        if (TestPanel._currentId) {
            window.open(`/test_detail/${TestPanel._currentId}`, '_blank');
        }
    },

    _injectStyles: () => {
        // Injecter les styles spécifiques de test_detail si pas déjà fait
        if (document.getElementById('test-panel-extra-styles')) return;
        const style = document.createElement('style');
        style.id = 'test-panel-extra-styles';
        style.textContent = `
            .test-panel-body .summary-chip { padding:5px 12px; border-radius:16px; font-size:0.84em; font-weight:600; display:inline-flex; align-items:center; gap:5px; }
            .test-panel-body .chip-ok       { background:#d4efdf; color:#1e8449; }
            .test-panel-body .chip-warning  { background:#fdebd0; color:#d35400; }
            .test-panel-body .chip-critical { background:#fadbd8; color:#c0392b; }
            .test-panel-body .chip-info     { background:#d6eaf8; color:#1a5276; }
            .test-panel-body .disk-header { display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:10px; padding-bottom:12px; border-bottom:1px solid var(--border); margin-bottom:14px; }
            .test-panel-body .disk-title  { display:flex; align-items:center; gap:8px; flex-wrap:wrap; }
            .test-panel-body .disk-title h2 { margin:0; font-size:1.15em; }
            .test-panel-body .health-pill { padding:3px 10px; border-radius:14px; font-size:0.82em; font-weight:600; }
            .test-panel-body .health-pill.ok       { background:var(--success); color:#fff; }
            .test-panel-body .health-pill.warning  { background:var(--warning); color:#2c3e50; }
            .test-panel-body .health-pill.critical { background:var(--danger); color:#fff; }
            .test-panel-body .temp-pill { padding:5px 12px; border-radius:16px; font-weight:700; color:#fff; font-size:0.88em; }
            .test-panel-body .temp-cool { background:#2ecc71; }
            .test-panel-body .temp-warm { background:#f39c12; color:#2c3e50; }
            .test-panel-body .temp-hot  { background:#e74c3c; }
            .test-panel-body .alert-box { border-radius:6px; padding:10px 14px; margin-bottom:12px; }
            .test-panel-body .alert-box.critical { background:#fadbd8; border-left:4px solid var(--danger); }
            .test-panel-body .alert-box.warning  { background:#fdebd0; border-left:4px solid var(--warning); }
            .test-panel-body .alert-box strong { display:block; margin-bottom:5px; }
            .test-panel-body .alert-box ul { margin:0 0 0 18px; }
            .test-panel-body .alert-box li { margin:3px 0; font-size:0.88em; }
            .test-panel-body .smart-cats { display:grid; grid-template-columns:repeat(auto-fit,minmax(140px,1fr)); gap:8px; margin:12px 0; }
            .test-panel-body .smart-cat { border-radius:6px; padding:10px; border:1px solid var(--border); }
            .test-panel-body .smart-cat.cat-ok       { background:#d4efdf; }
            .test-panel-body .smart-cat.cat-warning  { background:#fdebd0; }
            .test-panel-body .smart-cat.cat-critical { background:#fadbd8; }
            .test-panel-body .smart-cat-title { font-weight:700; font-size:0.82em; margin-bottom:3px; }
            .test-panel-body .smart-cat-value { font-size:1.5em; font-weight:700; }
            .test-panel-body .smart-cat-note  { font-size:0.74em; color:#7f8c8d; margin-top:2px; }
            .test-panel-body .metric-card { background:var(--bg); border-radius:8px; padding:12px; text-align:center; border:1px solid var(--border); }
            .test-panel-body .metric-value { font-size:1.5em; font-weight:700; color:var(--primary); line-height:1.1; }
            .test-panel-body .metric-unit  { font-size:0.6em; color:#7f8c8d; }
            .test-panel-body .metric-label { font-size:0.8em; color:#7f8c8d; margin-top:3px; }
            .test-panel-body .smart-section summary { cursor:pointer; padding:8px 12px; background:var(--bg); border-radius:6px; font-weight:600; user-select:none; }
            .test-panel-body .smart-section summary:hover { background:var(--hover); }
            .test-panel-body .smart-attr-critical td { background:#fff3cd !important; color:#856404; font-weight:500; }
            .test-panel-body .smart-attr-alert    td { background:#f8d7da !important; color:#721c24; font-weight:600; }
            .test-panel-body .tip { cursor:help; border-bottom:1px dashed #aaa; }
            .test-panel-body .nvme-note { background:#d6eaf8; border-left:4px solid var(--primary); padding:7px 12px; border-radius:4px; font-size:0.84em; color:#1a5276; margin-bottom:10px; }
            .test-panel-body .smart-error-banner { padding:10px 14px; background:#f8d7da; border-radius:6px; border-left:4px solid var(--danger); margin-bottom:10px; color:#721c24; font-size:0.88em; }
            .test-panel-body .back-link { display:none; }
        `;
        document.head.appendChild(style);
    }
};

// ═══════════════════════════════════════════════════════════════
// REPORTS LIST — mise à jour dynamique sans reload
// ═══════════════════════════════════════════════════════════════
const ReportsList = {
    // Ajouter une carte "Running" immédiatement après démarrage
    addRunning: (testId, name) => {
        const grid = document.getElementById('reports-list');
        if (!grid) return;
        // Éviter les doublons
        if (document.getElementById(`report-${testId}`)) return;

        const now = new Date().toLocaleDateString('fr-FR', {day:'2-digit', month:'2-digit', hour:'2-digit', minute:'2-digit'}).replace(',', '');
        const card = document.createElement('div');
        card.className = 'report-card running';
        card.id = `report-${testId}`;
        card.dataset.testId = testId;
        card.style.cursor = 'pointer';
        card.onclick = () => TestPanel.open(testId);
        card.innerHTML = `
            <div class="report-top">
                <strong>${name}</strong>
                <span class="date">${now}</span>
            </div>
            <div class="report-bottom">
                <span class="badge bg-warning">Running</span>
                <div class="actions">
                    <input type="checkbox" class="chart-toggle" value="${testId}"
                           onclick="event.stopPropagation();"
                           onchange="Charts.update(Charts.currentChartType);">
                    <button onclick="event.preventDefault(); event.stopPropagation(); Bench.deleteTest('${testId}')"
                            class="btn-delete" title="Supprimer">🗑️</button>
                </div>
            </div>`;
        grid.insertBefore(card, grid.firstChild);
    },

    // Mettre à jour le badge de statut d'une carte existante
    updateCard: (testId, status, progress) => {
        const card = document.getElementById(`report-${testId}`);
        if (!card) return;

        const badgeEl = card.querySelector('.badge');
        if (!badgeEl) return;

        const classMap = { Running:'bg-warning', Finished:'bg-success', Error:'bg-danger' };
        badgeEl.className = `badge ${classMap[status] || 'bg-danger'}`;
        badgeEl.textContent = status;
        card.className = `report-card ${status.toLowerCase()}`;

        // Ajouter barre de progression inline si Running
        let progBar = card.querySelector('.inline-prog');
        if (status === 'Running' && progress !== undefined) {
            if (!progBar) {
                progBar = document.createElement('div');
                progBar.className = 'inline-prog progress-bar-bg';
                progBar.style.cssText = 'margin:4px 0 0; height:3px;';
                progBar.innerHTML = '<div class="progress-bar-fill" style="height:3px; transition:width 0.5s;"></div>';
                card.appendChild(progBar);
            }
            progBar.querySelector('.progress-bar-fill').style.width = `${progress}%`;
        } else if (status !== 'Running' && progBar) {
            progBar.remove();
        }
    }
};

// Fermer le panel avec Escape
document.addEventListener('keydown', e => {
    if (e.key === 'Escape') TestPanel.close();
});

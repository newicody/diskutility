const socket = io();

// État global
const AppState = {
    activeTasks: [],
    charts: {},
    currentChartType: 'read'
};

// Interface utilisateur
const Backup = {
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
            Toolbox.addInstantTask(`Sauvegarde ${device}`, `→ ${destination}`);
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
                Toolbox.addInstantTask(`Sauvegarde ${source}`, `→ ${destination}`);
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
    // Vérifier si les détails sont déjà chargés
    if (card.querySelector('.disk-details')) return;
    
    try {
        const response = await fetch(`/get_disk_details/${deviceName}`);
        const data = await response.json();
        
        const detailsDiv = document.createElement('div');
        detailsDiv.className = 'disk-details';
        
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
        
        card.appendChild(detailsDiv);
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

    refresh: () => location.reload(),

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
                UI.showNotification('Test démarré avec succès', 'success');
                UI.toggleTasks();
                setTimeout(() => UI.refresh(), 1000);
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
                setTimeout(() => UI.refresh(), 500);
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

    // Options de log (lues depuis les checkboxes)
    getLogOptions: () => ({
        http:     document.getElementById('log-http')?.checked ?? true,
        commands: document.getElementById('log-commands')?.checked ?? true,
        output:   document.getElementById('log-output')?.checked ?? true,
        duration: document.getElementById('log-duration')?.checked ?? true,
        errors:   document.getElementById('log-errors')?.checked ?? true,
        progress: document.getElementById('log-progress')?.checked ?? false,
    }),

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
                if (testId) {
                    window.location.href = `/test_detail/${testId}`;
                }
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
    // Créer/réutiliser le tooltip element
    let tip = document.getElementById('svg-chart-tooltip');
    if (!tip) {
        tip = document.createElement('div');
        tip.id = 'svg-chart-tooltip';
        tip.style.cssText = `
            position: fixed; z-index: 20000; background: #2c3e50; color: white;
            padding: 8px 12px; border-radius: 6px; font-size: 0.82em; line-height: 1.5;
            pointer-events: none; opacity: 0; transition: opacity 0.2s;
            white-space: pre-line; max-width: 280px; box-shadow: 0 4px 12px rgba(0,0,0,0.3);
        `;
        document.body.appendChild(tip);
    }

    // Lier les événements sur tous les éléments avec data-test-id ou title
    const points = container.querySelectorAll('[data-test-id], circle[title], .clickable-point');
    points.forEach(point => {
        point.style.cursor = 'pointer';

        point.addEventListener('mouseenter', (e) => {
            const titleText = point.getAttribute('title') || point.getAttribute('data-tooltip') || '';
            if (titleText) {
                tip.textContent = titleText;
                tip.style.opacity = '1';
            }
        });

        point.addEventListener('mousemove', (e) => {
            tip.style.left = (e.clientX + 15) + 'px';
            tip.style.top = (e.clientY - 10) + 'px';
        });

        point.addEventListener('mouseleave', () => {
            tip.style.opacity = '0';
        });

        point.addEventListener('click', (e) => {
            e.stopPropagation();
            const testId = point.getAttribute('data-test-id');
            if (testId) {
                window.location.href = `/test_detail/${testId}`;
            }
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
    document.getElementById('backup-progress-bar').style.width = '50%'; // À améliorer
    document.getElementById('backup-status').textContent = data.progress;
});

socket.on('backup_complete', (data) => {
    if (data.status === 'success') {
        UI.showNotification(data.message, 'success');
        document.getElementById('backup-progress-bar').style.width = '100%';
        setTimeout(() => Backup.closeModal(), 2000);
    } else {
        UI.showNotification(data.message, 'error');
    }
});

socket.on('sys_stats', (stats) => {
    document.getElementById('stat-users').innerText = stats.users;
    document.getElementById('stat-io').innerText = stats.io;
});
socket.on('progress_update', (data) => {
    Toolbox.handleProgressUpdate(data);
    
    // Mettre à jour les icônes de santé
    if (data.status === 'Finished' && data.data) {
        Object.keys(data.data).forEach(diskName => {
            const cleanName = diskName.replace('/dev/', '');
            const healthIcon = document.getElementById(`health-${cleanName}`);
            if (healthIcon && data.data[diskName].smart) {
                const hasErrors = data.data[diskName].smart.critical_alerts?.length > 0;
                healthIcon.innerText = hasErrors ? '🔴' : '🟢';
            }
        });
    }
});

// Initialisation
document.addEventListener('DOMContentLoaded', () => {
    Charts.init();
    
    // Gestionnaire de clic sur les cartes de rapport
    document.querySelectorAll('.report-card').forEach(card => {
        card.addEventListener('click', (e) => {
            if (!e.target.closest('input') && !e.target.closest('button')) {
                const href = card.getAttribute('href');
                if (href) window.location.href = href;
            }
        });
    });
    
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
    
    // Ajouter l'icône d'expansion si elle n'existe pas déjà
    if (!card.querySelector('.expand-icon')) {
        const expandIcon = document.createElement('span');
        expandIcon.className = 'expand-icon';
        expandIcon.innerHTML = '🔽';
        expandIcon.title = 'Déplier / Replier';
        card.appendChild(expandIcon);
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

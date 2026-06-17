import React, { useEffect, useMemo, useState } from 'react';
import { createRoot } from 'react-dom/client';
import './style.css';

const API_URL = (window.location.protocol === 'file:' || window.location.hostname === 'localhost' || window.location.hostname === '127.0.0.1') ? 'http://127.0.0.1:8000' : 'https://mmotors-back.onrender.com';
const STATUS_LABELS = { pending: 'En attente', accepted: 'Validé', refused: 'Refusé' };
const MODE_LABELS = { sale: 'Achat', rental: 'Location' };
const STATUS_CLASS = { pending: 'warning', accepted: 'success', refused: 'danger' };

function App() {
  const [token, setToken] = useState(localStorage.getItem('token') || '');
  const [role, setRole] = useState(localStorage.getItem('role') || '');
  const [email, setEmail] = useState(localStorage.getItem('email') || '');
  const [view, setView] = useState(token ? 'dashboard' : 'home');
  const [tokenError, setTokenError] = useState(false);
  const [vehicles, setVehicles] = useState([]);
  const [applications, setApplications] = useState([]);
  const [documents, setDocuments] = useState({});
  const [logs, setLogs] = useState([]);
  const [filter, setFilter] = useState('');
  const [search, setSearch] = useState('');
  const [message, setMessage] = useState('');
  const [health, setHealth] = useState({ label: 'Backend non vérifié', ok: false });
  const [loginForm, setLoginForm] = useState({ email: '', password: '' });
  const [register, setRegister] = useState({ full_name: '', email: '', password: '' });
  const [applicationForm, setApplicationForm] = useState({ vehicle_id: '', mode: 'sale', message: '' });
  const [decisionComment, setDecisionComment] = useState('');
  const [newVehicle, setNewVehicle] = useState({ brand: '', model: '', year: 2022, mileage: 20000, price: 250, mode: 'rental' });

  const authHeaders = useMemo(() => ({ Authorization: `Bearer ${token}`, 'Content-Type': 'application/json' }), [token]);
  const isAdmin = role === 'admin';
  const isUser = role === 'user';

  async function apiFetch(path, options = {}) {
    const response = await fetch(`${API_URL}${path}`, options);
    const data = await response.json().catch(() => ({}));
    if (!response.ok) throw new Error(data.detail || 'Erreur serveur');
    return data;
  }

  async function checkHealth() {
    try {
      const data = await apiFetch('/health');
      setHealth({ ok: true, label: `Backend OK · BDD ${data.database} · RPO ${data.rpo} · RTO ${data.rto}` });
    } catch (_) {
      setHealth({ ok: false, label: 'Backend Render indisponible : vérifie le service Render' });
    }
  }

  async function loadVehicles() {
    try {
      const query = filter ? `?mode=${filter}` : '';
      setVehicles(await apiFetch(`/vehicles${query}`));
    } catch (_) {
      setMessage('Impossible de charger les véhicules : vérifie que le backend FastAPI est lancé.');
    }
  }

  async function loadApplications() {
    if (!token) return setApplications([]);
    try {
      const data = await apiFetch('/applications', { headers: authHeaders });
      setApplications(data);
      data.forEach(app => loadDocuments(app.id).catch(() => {}));
    } catch (error) {
      if (String(error.message).toLowerCase().includes('token')) setTokenError(true);
      setMessage(error.message);
    }
  }

  async function loadDocuments(applicationId) {
    const data = await apiFetch(`/applications/${applicationId}/documents`, { headers: authHeaders });
    setDocuments(prev => ({ ...prev, [applicationId]: data }));
  }

  async function loadLogs() {
    if (!isAdmin) return;
    try {
      const data = await apiFetch('/admin/logs', { headers: authHeaders });
      setLogs(data.logs || []);
    } catch (error) {
      setMessage(error.message);
    }
  }

  useEffect(() => { checkHealth(); loadVehicles(); }, [filter]);
  useEffect(() => { loadApplications(); }, [token]);
  useEffect(() => { loadLogs(); }, [role, token]);
  useEffect(() => {
    if (vehicles.length && !applicationForm.vehicle_id) {
      const first = vehicles[0];
      setApplicationForm(prev => ({ ...prev, vehicle_id: first.id, mode: first.mode }));
    }
  }, [vehicles]);

  async function login(event) {
    event.preventDefault();
    try {
      const data = await apiFetch('/auth/login', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(loginForm),
      });
      localStorage.setItem('token', data.access_token);
      localStorage.setItem('role', data.role);
      localStorage.setItem('email', loginForm.email);
      setToken(data.access_token); setRole(data.role); setEmail(loginForm.email); setTokenError(false);
      setMessage(`Connexion réussie : ${data.role === 'admin' ? 'administrateur' : 'client'}`);
      setView('dashboard');
    } catch (error) { setMessage(error.message); }
  }


  async function createAccount(event) {
    event.preventDefault();
    try {
      const data = await apiFetch('/auth/register', {
        method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(register),
      });
      localStorage.setItem('token', data.access_token);
      localStorage.setItem('role', data.role);
      localStorage.setItem('email', register.email);
      setToken(data.access_token); setRole(data.role); setEmail(register.email); setView('dashboard');
      setMessage('Compte client créé et connecté');
    } catch (error) { setMessage(error.message); }
  }

  function logout() {
    localStorage.clear();
    setToken(''); setRole(''); setEmail(''); setApplications([]); setDocuments({}); setLogs([]); setView('home');
    setMessage('Déconnexion effectuée');
  }

  async function createApplication(vehicle) {
    if (!isUser) { setMessage('Connecte-toi avec le compte user pour déposer un dossier.'); setView('login'); return; }
    try {
      await apiFetch('/applications', {
        method: 'POST', headers: authHeaders,
        body: JSON.stringify({ vehicle_id: vehicle.id, mode: vehicle.mode, message: 'Dossier déposé depuis le portail client' }),
      });
      setMessage('Dossier créé. Ajoute maintenant une pièce justificative PDF/JPG/PNG depuis ton espace client.');
      setView('applications');
      await loadApplications();
    } catch (error) { setMessage(error.message); }
  }

  async function createManualApplication(event) {
    event.preventDefault();
    const selected = vehicles.find(v => Number(v.id) === Number(applicationForm.vehicle_id));
    if (!selected) return setMessage('Sélectionne un véhicule');
    await createApplication({ ...selected, mode: applicationForm.mode || selected.mode });
  }

  async function uploadDocument(applicationId, file) {
    if (!file) return;
    const formData = new FormData(); formData.append('file', file);
    try {
      const response = await fetch(`${API_URL}/applications/${applicationId}/documents`, {
        method: 'POST', headers: { Authorization: `Bearer ${token}` }, body: formData,
      });
      const data = await response.json().catch(() => ({}));
      if (!response.ok) throw new Error(data.detail || 'Upload impossible');
      setMessage(`Document ajouté : ${data.filename}`);
      await loadApplications();
    } catch (error) { setMessage(error.message); }
  }

  function openDocument(documentId) {
    window.open(`${API_URL}/documents/${documentId}?token=${encodeURIComponent(token)}`, '_blank');
  }

  async function addVehicle(event) {
    event.preventDefault();
    try {
      await apiFetch('/vehicles', {
        method: 'POST', headers: authHeaders,
        body: JSON.stringify({ ...newVehicle, year: Number(newVehicle.year), mileage: Number(newVehicle.mileage), price: Number(newVehicle.price) }),
      });
      setNewVehicle({ brand: '', model: '', year: 2022, mileage: 20000, price: 250, mode: 'rental' });
      setMessage('Véhicule ajouté en base'); await loadVehicles();
    } catch (error) { setMessage(error.message); }
  }

  async function switchVehicle(id) {
    try {
      await apiFetch(`/vehicles/${id}/switch`, { method: 'PATCH', headers: authHeaders });
      setMessage('Véhicule basculé achat/location'); await loadVehicles();
    } catch (error) { setMessage(error.message); }
  }

  async function decideApplication(id, status) {
    try {
      await apiFetch(`/applications/${id}/decision`, {
        method: 'PATCH', headers: authHeaders,
        body: JSON.stringify({ status, admin_comment: decisionComment || (status === 'accepted' ? 'Dossier validé par le back-office' : 'Dossier refusé : pièces à compléter') }),
      });
      setMessage(status === 'accepted' ? 'Dossier validé' : 'Dossier refusé avec motif');
      await loadApplications();
    } catch (error) { setMessage(error.message); }
  }

  async function testAlert() {
    try { await apiFetch('/health/alert-test', { method: 'POST', headers: authHeaders }); setMessage('Alerte de test enregistrée'); await loadLogs(); }
    catch (error) { setMessage(error.message); }
  }

  const filteredVehicles = vehicles.filter(v => `${v.brand} ${v.model}`.toLowerCase().includes(search.toLowerCase()));
  const metrics = {
    vehicles: vehicles.length,
    dossiers: applications.length,
    pending: applications.filter(a => a.status === 'pending').length,
    docs: applications.reduce((sum, a) => sum + Number(a.documents_count || 0), 0),
  };

  return (
    <main>
      <nav className="topbar">
        <button className="brand" onClick={() => setView('home')}>DriveOps<br/>M-Motors</button>
        <div className="navlinks">
          <button className={view === 'vehicles' ? 'active' : ''} onClick={() => setView('vehicles')}>Véhicules</button>
          {token && <button className={view === 'dashboard' ? 'active' : ''} onClick={() => setView('dashboard')}>Espace {isAdmin ? 'admin' : 'client'}</button>}
          {token && <button className={view === 'applications' ? 'active' : ''} onClick={() => setView('applications')}>Dossiers</button>}
          {isAdmin && <button className={view === 'adminVehicles' ? 'active' : ''} onClick={() => setView('adminVehicles')}>Back-office</button>}
          {isAdmin && <button className={view === 'monitoring' ? 'active' : ''} onClick={() => setView('monitoring')}>Monitoring</button>}
        </div>
        <div className="account">
          {token ? <><span>{email}</span><button className="outline" onClick={logout}>Déconnexion</button></> : <button onClick={() => setView('login')}>Connexion</button>}
        </div>
      </nav>

      {message && <div className="notice"><span>Info</span>{message}</div>}
      {tokenError && <div className="notice danger-note"><span>Session</span>Reconnecte-toi : ton token local semble expiré.</div>}

      {view === 'home' && <Home setView={setView} health={health} />}
      {view === 'login' && <Login login={login} loginForm={loginForm} setLoginForm={setLoginForm} register={register} setRegister={setRegister} createAccount={createAccount} />}
      {view === 'vehicles' && <Vehicles vehicles={filteredVehicles} search={search} setSearch={setSearch} filter={filter} setFilter={setFilter} role={role} createApplication={createApplication} switchVehicle={switchVehicle} />}
      {view === 'dashboard' && token && <Dashboard role={role} email={email} metrics={metrics} setView={setView} health={health} />}
      {view === 'applications' && token && <Applications applications={applications} documents={documents} role={role} vehicles={vehicles} uploadDocument={uploadDocument} openDocument={openDocument} decideApplication={decideApplication} decisionComment={decisionComment} setDecisionComment={setDecisionComment} applicationForm={applicationForm} setApplicationForm={setApplicationForm} createManualApplication={createManualApplication} />}
      {view === 'adminVehicles' && isAdmin && <AdminVehicles vehicles={vehicles} newVehicle={newVehicle} setNewVehicle={setNewVehicle} addVehicle={addVehicle} switchVehicle={switchVehicle} />}
      {view === 'monitoring' && isAdmin && <Monitoring health={health} logs={logs} loadLogs={loadLogs} testAlert={testAlert} />}
    <footer className="footer"><strong>Projet Bachelor Développeur Web</strong> · Saadan Walid · Bloc 3</footer>
    </main>
  );
}

function Home({ setView, health }) {
  return <section className="heroPro">
    <div className="heroContent">
      <p className="eyebrow">Vente et location longue durée</p>
      <h1>DriveOps, portail métier M-Motors</h1>
      <p>Un espace métier complet pour piloter les offres achat/LLD, les dossiers clients, les justificatifs et la supervision applicative.</p>
      <div className="heroActions"><button onClick={() => setView('vehicles')}>Rechercher un véhicule</button><button className="secondary" onClick={() => setView('login')}>Accéder à mon espace</button></div>
      <div className={`health-pill ${health.ok ? 'ok' : ''}`}>{health.label}</div>
    </div>
    <div className="heroPanel">
      <h2>Parcours dossier sécurisé</h2>
      <ul><li>Connexion par compte sécurisé</li><li>Justificatifs consultables et téléchargeables</li><li>Décision back-office tracée</li><li>Supervision Prometheus / Grafana</li></ul>
    </div>
  </section>;
}

function Login(props) {
  const { login, loginForm, setLoginForm, register, setRegister, createAccount } = props;
  return <section className="twoCols narrow">
    <div className="card authCard"><p className="eyebrow">Portail d’accès</p><h1>Connexion</h1><form onSubmit={login} className="stack">
      <label>Email<input type="email" value={loginForm.email} onChange={e => setLoginForm({ ...loginForm, email: e.target.value })} required /></label>
      <label>Mot de passe<input type="password" value={loginForm.password} onChange={e => setLoginForm({ ...loginForm, password: e.target.value })} required /></label>
      <button>Se connecter</button>
    </form></div>
    <div className="card authCard"><p className="eyebrow">Créer un accès client</p><h1>Créer un compte</h1><form onSubmit={createAccount} className="stack">
      <label>Nom complet<input value={register.full_name} onChange={e => setRegister({ ...register, full_name: e.target.value })} required /></label>
      <label>Email<input type="email" value={register.email} onChange={e => setRegister({ ...register, email: e.target.value })} required /></label>
      <label>Mot de passe<input type="password" value={register.password} onChange={e => setRegister({ ...register, password: e.target.value })} required /></label>
      <button className="secondary">Créer mon espace</button>
    </form></div>
  </section>;
}

function Vehicles({ vehicles, search, setSearch, filter, setFilter, role, createApplication, switchVehicle }) {
  return <section className="page"><div className="pageHead"><div><p className="eyebrow">Catalogue</p><h1>Catalogue opérationnel</h1></div><div className="segmented"><button className={filter === '' ? 'active' : ''} onClick={() => setFilter('')}>Tous</button><button className={filter === 'sale' ? 'active' : ''} onClick={() => setFilter('sale')}>Achat</button><button className={filter === 'rental' ? 'active' : ''} onClick={() => setFilter('rental')}>Location</button></div></div>
    <div className="searchLine"><input placeholder="Marque ou modèle" value={search} onChange={e => setSearch(e.target.value)} /><button>Filtrer</button></div>
    <div className="vehicleGrid">{vehicles.map(vehicle => <article className="vehiclePro" key={vehicle.id}><div className="vehicleTop"><span className={`mode ${vehicle.mode}`}>{MODE_LABELS[vehicle.mode]}</span><span>{vehicle.year}</span></div><h3>{vehicle.brand} {vehicle.model}</h3><p>{vehicle.mileage.toLocaleString('fr-FR')} km · {vehicle.mode === 'sale' ? 'Vente directe' : 'Location avec option d’achat'}</p><strong>{vehicle.mode === 'sale' ? `${vehicle.price.toLocaleString('fr-FR')} €` : `${vehicle.price} €/mois`}</strong><button disabled={role !== 'user'} onClick={() => createApplication(vehicle)}>Déposer un dossier</button>{role === 'admin' && <button className="ghost full" onClick={() => switchVehicle(vehicle.id)}>Basculer achat/location</button>}</article>)}</div>
  </section>;
}

function Dashboard({ role, email, metrics, setView, health }) {
  return <section className="page"><p className="eyebrow">Espace {role === 'admin' ? 'administrateur' : 'client'}</p><h1>Bonjour {email}</h1><div className="stats"><div><span>{metrics.vehicles}</span><p>Véhicules</p></div><div><span>{metrics.dossiers}</span><p>Dossiers</p></div><div><span>{metrics.pending}</span><p>En attente</p></div><div><span>{metrics.docs}</span><p>Documents</p></div></div><div className="actionCards"><div className="card"><h2>Catalogue</h2><p>Consulter les véhicules disponibles à l’achat ou à la location.</p><button onClick={() => setView('vehicles')}>Voir les véhicules</button></div><div className="card"><h2>Dossiers</h2><p>Suivre les demandes, pièces justificatives, décisions et commentaires.</p><button className="secondary" onClick={() => setView('applications')}>Voir les dossiers</button></div>{role === 'admin' && <div className="card"><h2>Back-office</h2><p>Ajouter des véhicules, basculer les modes et surveiller l’application.</p><button onClick={() => setView('adminVehicles')}>Administrer</button></div>}<div className="card"><h2>État système</h2><p>{health.label}</p></div></div></section>;
}

function Applications({ applications, documents, role, vehicles, uploadDocument, openDocument, decideApplication, decisionComment, setDecisionComment, applicationForm, setApplicationForm, createManualApplication }) {
  return <section className="page"><div className="pageHead"><div><p className="eyebrow">{role === 'admin' ? 'Back-office' : 'Dossier client'}</p><h1>{role === 'admin' ? 'Dossiers clients' : 'Mes dossiers'}</h1></div></div>
    {role === 'user' && <div className="card formCard"><h2>Déposer un nouveau dossier</h2><form onSubmit={createManualApplication} className="formGrid"><label>Véhicule<select value={applicationForm.vehicle_id} onChange={e => { const v = vehicles.find(x => Number(x.id) === Number(e.target.value)); setApplicationForm({ ...applicationForm, vehicle_id: e.target.value, mode: v?.mode || applicationForm.mode }); }} required>{vehicles.map(v => <option key={v.id} value={v.id}>{v.brand} {v.model} · {MODE_LABELS[v.mode]}</option>)}</select></label><label>Type<select value={applicationForm.mode} onChange={e => setApplicationForm({ ...applicationForm, mode: e.target.value })}><option value="sale">Achat</option><option value="rental">Location</option></select></label><label className="wide">Message<textarea placeholder="Informations utiles pour l’étude du dossier" value={applicationForm.message} onChange={e => setApplicationForm({ ...applicationForm, message: e.target.value })}></textarea></label><button>Envoyer le dossier</button></form></div>}
    {role === 'admin' && <div className="card"><label>Commentaire de décision<input placeholder="Commentaire envoyé au client" value={decisionComment} onChange={e => setDecisionComment(e.target.value)} /></label></div>}
    <div className="tableCard"><table><thead><tr><th>Dossier</th><th>Véhicule</th><th>Type</th><th>Statut</th><th>Documents</th><th>Actions</th></tr></thead><tbody>{applications.map(app => <tr key={app.id}><td>#{app.id}</td><td>Véhicule #{app.vehicle_id}</td><td>{MODE_LABELS[app.mode]}</td><td><span className={`status ${STATUS_CLASS[app.status]}`}>{STATUS_LABELS[app.status]}</span></td><td><div className="docList">{(documents[app.id] || []).length ? documents[app.id].map(doc => <button key={doc.id} className="doc" onClick={() => openDocument(doc.id)}>📄 {doc.filename}</button>) : <span>0</span>}</div></td><td><div className="actions">{role === 'user' && <label className="upload">Ajouter pièce<input type="file" accept="application/pdf,image/png,image/jpeg" onChange={e => uploadDocument(app.id, e.target.files[0])} /></label>}{role === 'admin' && <><button onClick={() => decideApplication(app.id, 'accepted')}>Valider</button><button className="red" onClick={() => decideApplication(app.id, 'refused')}>Refuser</button></>}</div><small>{app.admin_comment || app.message}</small></td></tr>)}</tbody></table>{applications.length === 0 && <p className="empty">Aucun dossier pour le moment.</p>}</div>
  </section>;
}

function AdminVehicles({ vehicles, newVehicle, setNewVehicle, addVehicle, switchVehicle }) {
  return <section className="page"><p className="eyebrow">Back-office</p><h1>Pilotage du catalogue</h1><div className="twoCols"><div className="card"><h2>Ajouter un véhicule</h2><form onSubmit={addVehicle} className="stack"><label>Marque<input value={newVehicle.brand} onChange={e => setNewVehicle({ ...newVehicle, brand: e.target.value })} required /></label><label>Modèle<input value={newVehicle.model} onChange={e => setNewVehicle({ ...newVehicle, model: e.target.value })} required /></label><div className="formGrid"><label>Année<input type="number" value={newVehicle.year} onChange={e => setNewVehicle({ ...newVehicle, year: e.target.value })} /></label><label>Kilométrage<input type="number" value={newVehicle.mileage} onChange={e => setNewVehicle({ ...newVehicle, mileage: e.target.value })} /></label></div><div className="formGrid"><label>Prix / mensualité<input type="number" value={newVehicle.price} onChange={e => setNewVehicle({ ...newVehicle, price: e.target.value })} /></label><label>Mode<select value={newVehicle.mode} onChange={e => setNewVehicle({ ...newVehicle, mode: e.target.value })}><option value="sale">Achat</option><option value="rental">Location</option></select></label></div><button>Ajouter en catalogue</button></form></div><div className="tableCard"><table><thead><tr><th>Véhicule</th><th>Mode</th><th>Prix</th><th>Action</th></tr></thead><tbody>{vehicles.map(v => <tr key={v.id}><td>{v.brand} {v.model}</td><td>{MODE_LABELS[v.mode]}</td><td>{v.mode === 'sale' ? `${v.price} €` : `${v.price} €/mois`}</td><td><button className="outline" onClick={() => switchVehicle(v.id)}>Basculer</button></td></tr>)}</tbody></table></div></div></section>;
}

function Monitoring({ health, logs, loadLogs, testAlert }) {
  return <section className="page"><div className="pageHead"><div><p className="eyebrow">Supervision</p><h1>Observabilité et alerting</h1></div><div className="actions"><button onClick={testAlert}>Tester alerting</button><button className="outline" onClick={loadLogs}>Rafraîchir</button></div></div><div className="stats"><div><span>{health.ok ? 'OK' : 'KO'}</span><p>Healthcheck</p></div><div><span>15 min</span><p>RPO</p></div><div><span>1 h</span><p>RTO</p></div><div><span>{logs.length}</span><p>Logs</p></div></div><pre className="logs">{logs.length ? logs.join('\n') : 'Aucune alerte enregistrée pour le moment.'}</pre></section>;
}

createRoot(document.getElementById('root')).render(<App />);

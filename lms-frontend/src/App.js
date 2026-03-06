// lms-frontend/src/App.js
import React, { useState, useEffect } from 'react';
import axios from 'axios';
import { Auth0Provider, useAuth0 } from '@auth0/auth0-react';

function App() {
    const { loginWithRedirect, isAuthenticated, user } = useAuth0();
    const [userData, setUserData] = useState(null);
    const [videos, setVideos] = useState([]);
    const [recommendations, setRecommendations] = useState([]);
    const [messages, setMessages] = useState([]);

    useEffect(() => {
        if (isAuthenticated) {
            axios.post('http://localhost:3000/api/auth0/callback', { token: user.sub })
                .then(res => {
                    setUserData(res.data);
                    axios.get(`http://localhost:5000/upload?language=${res.data.language}`)
                        .then(vidRes => setVideos(vidRes.data.videos));
                    axios.get(`http://localhost:3000/api/recommendations/${res.data.userId}`)
                        .then(recRes => setRecommendations(recRes.data.recommendations));
                    axios.get(`http://localhost:3000/api/dashboard/${res.data.userId}`)
                        .then(dashRes => setMessages(dashRes.data.messages));
                });
        }
    }, [isAuthenticated, user]);

    if (!isAuthenticated) return <button onClick={() => loginWithRedirect()}>Log in with Google/School Account</button>;

    return (
        <div className="min-h-screen bg-gray-100 p-8">
            <h1 className="text-2xl font-bold mb-4">Student Dashboard ({userData?.language})</h1>
            <div className="mb-4">
                <h2 className="text-xl font-bold">Improvement Tips</h2>
                <ul className="list-disc pl-5">
                    {messages.map((msg, i) => <li key=i>{msg.message} <a href={`/vr/{msg.topic}`} className="text-blue-500">Try VR</a></li>)}
                </ul>
            </div>
            <div className="mb-4">
                <h2 className="text-xl font-bold">Recommended for You</h2>
                <ul className="list-disc pl-5">
                    {recommendations.map((rec, i) => <li key=i>{rec}</li>)}
                </ul>
            </div>
            <div className="grid grid-cols-3 gap-4">
                {videos.map(vid => (
                    <div key={vid} className="bg-white p-4 rounded shadow">
                        <video src={`/video/{vid}`} controls className="w-full" />
                        <button onClick={() => window.open(`/vr/{vid.split('_')[0]}`, '_blank')} className="mt-2 bg-blue-500 text-white p-2 rounded">
                            Launch VR Sim
                        </button>
                    </div>
                ))}
            </div>
        </div>
    );
}

export default function WrappedApp() {
    return (
        <Auth0Provider
            domain={process.env.REACT_APP_AUTH0_DOMAIN}
            clientId={process.env.REACT_APP_AUTH0_CLIENT_ID}
            redirectUri={window.location.origin}
        >
            <App />
        </Auth0Provider>
    );
}

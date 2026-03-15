'use client';

import Link from 'next/link';

export default function LandingPage() {
  return (
    <div className="landing">
      <div className="orb orb-1" />
      <div className="orb orb-2" />
      <div className="orb orb-3" />
      <div className="landing-content">
        <div className="landing-icon">🧠</div>
        <h1>Bonat Brain</h1>
        <p>AI-powered business intelligence for your merchant data</p>
        <div className="landing-actions">
          <Link href="/login" className="btn btn-primary">Sign In</Link>
          <Link href="/register" className="btn btn-secondary">Create Account</Link>
        </div>
      </div>
    </div>
  );
}

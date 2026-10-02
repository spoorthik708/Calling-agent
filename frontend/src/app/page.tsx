import React from "react";

export default function Home() {
  const pillars = [
    {
      title: "Core Product Principle",
      badge: "Non-Negotiable",
      badgeColor: "bg-amber-500/10 text-amber-400 border-amber-500/20",
      description:
        "The AI model handles understanding and conversation. The application and verified business systems own factual truth. Hallucinating prices, policies, or availability is strictly prohibited.",
    },
    {
      title: "Multi-Tenant SaaS Boundary",
      badge: "Enterprise Security",
      badgeColor: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
      description:
        "Strict backend tenant context isolation. TenantAwareModel mixin, ContextVar execution scoping, and foreign key boundaries ensure zero cross-tenant data leakage.",
    },
    {
      title: "Modular AI Provider Layer",
      badge: "Vendor Agnostic",
      badgeColor: "bg-indigo-500/10 text-indigo-400 border-indigo-500/20",
      description:
        "Business logic is decoupled from external model APIs via AIProviderInterface and ToolRegistry with safety guardrails against injection or arbitrary execution.",
    },
    {
      title: "Future Real-Time Voice Layer",
      badge: "Interface Ready",
      badgeColor: "bg-sky-500/10 text-sky-400 border-sky-500/20",
      description:
        "Prepared boundaries for bi-directional audio streaming, barge-in / interruption handling, and telephony provider integration (Twilio / LiveKit / SIP).",
    },
  ];

  return (
    <main className="min-h-screen p-8 md:p-16 max-w-7xl mx-auto flex flex-col justify-between">
      {/* Header */}
      <div>
        <div className="flex items-center justify-between pb-8 border-b border-gray-800">
          <div className="flex items-center space-x-3">
            <div className="h-10 w-10 rounded-xl bg-gradient-to-tr from-indigo-600 to-violet-400 flex items-center justify-center font-bold text-white shadow-lg shadow-indigo-500/20">
              Y
            </div>
            <div>
              <h1 className="text-xl font-bold tracking-tight text-white">YAVURA</h1>
              <p className="text-xs text-gray-400">Enterprise AI Conversational Platform</p>
            </div>
          </div>
          <div className="flex items-center space-x-2">
            <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium bg-emerald-500/10 text-emerald-400 border border-emerald-500/20">
              <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 mr-2 animate-pulse" />
              Foundation Active (v0.1.0)
            </span>
          </div>
        </div>

        {/* Hero */}
        <div className="py-12 md:py-16">
          <div className="max-w-3xl">
            <h2 className="text-3xl md:text-5xl font-extrabold tracking-tight text-white leading-tight">
              Production-Grade Foundation & Architecture
            </h2>
            <p className="mt-4 text-lg text-gray-300 leading-relaxed">
              YAVURA enables businesses to deploy verified, real-time conversational voice agents. Built on strict backend tenant isolation, factual truth enforcement, and modular AI provider abstractions.
            </p>
          </div>
        </div>

        {/* Architectural Pillars */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6 mt-4">
          {pillars.map((pillar, idx) => (
            <div
              key={idx}
              className="p-6 rounded-2xl bg-gray-900/60 border border-gray-800 backdrop-blur-sm hover:border-gray-700 transition duration-200"
            >
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-lg font-semibold text-white">{pillar.title}</h3>
                <span className={`text-xs px-2.5 py-0.5 rounded-full border ${pillar.badgeColor}`}>
                  {pillar.badge}
                </span>
              </div>
              <p className="text-sm text-gray-400 leading-relaxed">{pillar.description}</p>
            </div>
          ))}
        </div>

        {/* System Health Check Verification */}
        <div className="mt-8 p-6 rounded-2xl bg-indigo-950/20 border border-indigo-900/30">
          <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-4">
            <div>
              <h4 className="text-sm font-semibold text-indigo-200">Backend Infrastructure Health</h4>
              <p className="text-xs text-indigo-300/70 mt-1">
                FastAPI service endpoint responding on <code className="px-1.5 py-0.5 rounded bg-black/40 text-indigo-200">GET /health</code>
              </p>
            </div>
            <div className="flex items-center space-x-3 text-xs font-mono text-gray-300">
              <span className="px-3 py-1.5 rounded-lg bg-black/40 border border-gray-800">
                Service: yavura-api
              </span>
              <span className="px-3 py-1.5 rounded-lg bg-black/40 border border-gray-800">
                Status: healthy
              </span>
            </div>
          </div>
        </div>
      </div>

      {/* Footer */}
      <footer className="pt-16 pb-4 border-t border-gray-900 text-xs text-gray-400 flex flex-col sm:flex-row items-center justify-between gap-2">
        <p>&copy; {new Date().getFullYear()} YAVURA SaaS. Production Architecture Foundation.</p>
        <p>Tenant-Isolated &bull; Grounded Knowledge &bull; Modular Voice AI</p>
      </footer>
    </main>
  );
}

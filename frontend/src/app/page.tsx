"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import { Navigation } from "@/components/Navigation";
import {
  PhoneCall,
  Megaphone,
  BarChart3,
  ShieldCheck,
  Cpu,
  Layers,
  ArrowRight,
  Activity,
  CheckCircle2,
  Clock,
} from "lucide-react";

export default function Home() {
  const [stats, setStats] = useState<{
    total_calls: number;
    completed_calls: number;
    average_duration_seconds: number;
  } | null>(null);

  useEffect(() => {
    fetch("/api/v1/telephony/analytics")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (data) {
          setStats({
            total_calls: data.total_calls,
            completed_calls: data.completed_calls,
            average_duration_seconds: data.average_duration_seconds,
          });
        }
      })
      .catch(() => {});
  }, []);

  const features = [
    {
      title: "Call History & Audit",
      description: "Real-time logging of inbound & outbound call sessions, state callbacks, and audio recording access.",
      href: "/calls",
      icon: PhoneCall,
      color: "text-purple-400 bg-purple-500/10 border-purple-500/20",
    },
    {
      title: "Calling Campaigns",
      description: "Automated batch phone call dispatching, target contact scheduling, and execution progress tracking.",
      href: "/campaigns",
      icon: Megaphone,
      color: "text-indigo-400 bg-indigo-500/10 border-indigo-500/20",
    },
    {
      title: "Telephony Analytics",
      description: "Deep insights into call volume, success & completion rates, traffic directions, and session duration.",
      href: "/analytics",
      icon: BarChart3,
      color: "text-emerald-400 bg-emerald-500/10 border-emerald-500/20",
    },
  ];

  const pillars = [
    {
      title: "Factually Grounded Truth",
      badge: "Strict Architecture",
      badgeColor: "bg-amber-500/10 text-amber-400 border-amber-500/20",
      description:
        "AI conversational models handle speech understanding. Core backend databases enforce strict factual boundaries to eliminate hallucinations.",
    },
    {
      title: "Multi-Tenant SaaS Boundary",
      badge: "Enterprise Security",
      badgeColor: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20",
      description:
        "Backend tenant context isolation with ContextVar scoping and database boundaries ensuring zero cross-tenant phone data or recording leakage.",
    },
    {
      title: "Twilio Telephony & Media Streams",
      badge: "Real-Time Transport",
      badgeColor: "bg-purple-500/10 text-purple-400 border-purple-500/20",
      description:
        "Full Twilio HMAC signature verification, WebSocket bi-directional audio bridge, sub-300ms barge-in interruption handling.",
    },
  ];

  return (
    <div className="min-h-screen bg-slate-950 text-slate-100 flex flex-col font-sans">
      <Navigation />

      <main className="flex-1 max-w-7xl w-full mx-auto px-4 sm:px-6 lg:px-8 py-8 space-y-10">
        {/* Hero Banner */}
        <div className="relative overflow-hidden rounded-3xl bg-gradient-to-r from-purple-950/50 via-slate-900 to-indigo-950/40 border border-purple-900/30 p-8 md:p-12 shadow-2xl">
          <div className="max-w-2xl space-y-4 relative z-10">
            <div className="inline-flex items-center space-x-2 px-3 py-1 rounded-full text-xs font-mono bg-purple-500/10 text-purple-300 border border-purple-500/20">
              <Activity className="w-3.5 h-3.5 text-purple-400 animate-pulse" />
              <span>Phase 7 Telephony Integration Active</span>
            </div>
            <h1 className="text-3xl md:text-5xl font-extrabold tracking-tight text-white leading-tight">
              Enterprise Voice & Telephony Control Center
            </h1>
            <p className="text-sm md:text-base text-slate-300 leading-relaxed">
              Deploy, monitor, and analyze verified real-time AI phone calls. Built on tenant-isolated WebSocket media streaming and Twilio PSTN integration.
            </p>
          </div>

          {/* Quick Metrics Badge Overlay */}
          {stats && (
            <div className="mt-8 grid grid-cols-1 sm:grid-cols-3 gap-4 border-t border-purple-900/20 pt-6">
              <div className="flex items-center space-x-3">
                <div className="p-2 rounded-xl bg-purple-500/10 border border-purple-500/20 text-purple-400">
                  <PhoneCall className="w-4 h-4" />
                </div>
                <div>
                  <span className="text-xs text-slate-400 block">Total Call Volume</span>
                  <span className="text-lg font-bold text-slate-100">{stats.total_calls} Sessions</span>
                </div>
              </div>
              <div className="flex items-center space-x-3">
                <div className="p-2 rounded-xl bg-emerald-500/10 border border-emerald-500/20 text-emerald-400">
                  <CheckCircle2 className="w-4 h-4" />
                </div>
                <div>
                  <span className="text-xs text-slate-400 block">Successful Calls</span>
                  <span className="text-lg font-bold text-slate-100">{stats.completed_calls} Completed</span>
                </div>
              </div>
              <div className="flex items-center space-x-3">
                <div className="p-2 rounded-xl bg-indigo-500/10 border border-indigo-500/20 text-indigo-400">
                  <Clock className="w-4 h-4" />
                </div>
                <div>
                  <span className="text-xs text-slate-400 block">Average Duration</span>
                  <span className="text-lg font-bold text-slate-100">{stats.average_duration_seconds}s / call</span>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Primary Feature Cards */}
        <div>
          <h2 className="text-lg font-bold text-slate-100 mb-4">Core Management Modules</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {features.map((feat) => {
              const Icon = feat.icon;
              return (
                <Link
                  key={feat.href}
                  href={feat.href}
                  className="group p-6 rounded-2xl bg-slate-900/60 border border-purple-900/20 hover:border-purple-500/40 transition duration-200 backdrop-blur-sm flex flex-col justify-between"
                >
                  <div className="space-y-4">
                    <div className={`p-3 rounded-xl inline-block border ${feat.color}`}>
                      <Icon className="w-5 h-5" />
                    </div>
                    <h3 className="text-base font-semibold text-slate-100 group-hover:text-purple-300 transition duration-150">
                      {feat.title}
                    </h3>
                    <p className="text-xs text-slate-400 leading-relaxed">{feat.description}</p>
                  </div>
                  <div className="mt-6 flex items-center text-xs font-medium text-purple-400 group-hover:translate-x-1 transition duration-150">
                    <span>Open Module</span>
                    <ArrowRight className="w-3.5 h-3.5 ml-1.5" />
                  </div>
                </Link>
              );
            })}
          </div>
        </div>

        {/* Architecture & Security Guarantees */}
        <div>
          <h2 className="text-lg font-bold text-slate-100 mb-4">Architectural Standards</h2>
          <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
            {pillars.map((pillar, idx) => (
              <div
                key={idx}
                className="p-6 rounded-2xl bg-slate-900/40 border border-slate-800 backdrop-blur-sm space-y-3"
              >
                <div className="flex items-center justify-between">
                  <h3 className="text-sm font-semibold text-slate-200">{pillar.title}</h3>
                  <span className={`text-[10px] px-2 py-0.5 rounded-full border font-mono ${pillar.badgeColor}`}>
                    {pillar.badge}
                  </span>
                </div>
                <p className="text-xs text-slate-400 leading-relaxed">{pillar.description}</p>
              </div>
            ))}
          </div>
        </div>
      </main>

      <footer className="border-t border-slate-900 py-6 text-center text-xs text-slate-500 font-mono">
        Multi-Tenant Telephony Platform &bull; Factual Grounding Enforced &bull; Twilio Media Stream Enabled
      </footer>
    </div>
  );
}

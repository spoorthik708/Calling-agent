"use client";

import React from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { PhoneCall, Megaphone, BarChart3, LayoutDashboard, Users } from "lucide-react";

export function Navigation() {
  const pathname = usePathname();

  const navItems = [
    { name: "Overview", href: "/", icon: LayoutDashboard },
    { name: "Contacts", href: "/contacts", icon: Users },
    { name: "Call History", href: "/calls", icon: PhoneCall },
    { name: "Campaigns", href: "/campaigns", icon: Megaphone },
    { name: "Analytics", href: "/analytics", icon: BarChart3 },
  ];

  return (
    <header className="sticky top-0 z-40 backdrop-blur-md bg-slate-950/80 border-b border-purple-900/20">
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8">
        <div className="flex items-center justify-between h-16">
          {/* Neutral Branding Container (Branding fields left blank per requirement) */}
          <div className="flex items-center space-x-3">
            <div className="h-9 w-9 rounded-xl bg-gradient-to-tr from-purple-600 via-indigo-600 to-violet-400 p-0.5 shadow-lg shadow-purple-500/20">
              <div className="h-full w-full bg-slate-950 rounded-[10px] flex items-center justify-center">
                <span className="h-2.5 w-2.5 rounded-full bg-purple-400 animate-pulse" />
              </div>
            </div>
            <div>
              <span className="text-sm font-semibold tracking-wide text-slate-200">
                {/* Brand Name Field Left Blank */}
              </span>
              <p className="text-[10px] text-purple-400/70 uppercase tracking-widest font-mono">
                Telephony Platform
              </p>
            </div>
          </div>

          {/* Navigation Links */}
          <nav className="flex items-center space-x-1 sm:space-x-2">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = pathname === item.href;
              return (
                <Link
                  key={item.href}
                  href={item.href}
                  className={`flex items-center space-x-2 px-3.5 py-2 rounded-xl text-xs font-medium transition-all duration-200 ${
                    isActive
                      ? "bg-purple-600/15 text-purple-300 border border-purple-500/30 shadow-sm shadow-purple-900/40"
                      : "text-slate-400 hover:text-slate-200 hover:bg-slate-900/60"
                  }`}
                >
                  <Icon className={`w-4 h-4 ${isActive ? "text-purple-400" : "text-slate-400"}`} />
                  <span className="hidden sm:inline">{item.name}</span>
                </Link>
              );
            })}
          </nav>
        </div>
      </div>
    </header>
  );
}

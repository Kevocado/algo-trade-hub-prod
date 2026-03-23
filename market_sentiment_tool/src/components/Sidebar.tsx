import { NavLink } from "react-router-dom";
import { Activity, CloudLightning, Trophy, LogOut } from "lucide-react";
import { useAuth } from "@/contexts/AuthContext";
import { Button } from "@/components/ui/button";

export function Sidebar() {
  const { signOut } = useAuth();

  const navItems = [
    { to: "/", label: "War Room", icon: Activity },
    { to: "/kalshi", label: "Prediction Lab", icon: CloudLightning },
    { to: "/sports", label: "Sports Desk", icon: Trophy },
  ];

  return (
    <div className="w-64 h-screen bg-card border-r border-border flex flex-col justify-between py-6 px-4 shrink-0">
      <div>
        <div className="flex items-center gap-3 px-2 mb-8">
          <div className="w-8 h-8 rounded-lg bg-primary/20 flex items-center justify-center">
            <Activity className="w-5 h-5 text-primary" />
          </div>
          <h1 className="font-bold text-lg tracking-tight">Trade Hub</h1>
        </div>

        <nav className="space-y-2">
          {navItems.map((item) => (
            <NavLink
              key={item.to}
              to={item.to}
              className={({ isActive }) =>
                `flex items-center gap-3 px-3 py-2.5 rounded-lg transition-colors text-sm font-medium ${
                  isActive
                    ? "bg-primary/10 text-primary"
                    : "text-muted-foreground hover:bg-muted hover:text-foreground"
                }`
              }
            >
              <item.icon className="w-4 h-4" />
              {item.label}
            </NavLink>
          ))}
        </nav>
      </div>

      <Button
        variant="ghost"
        className="w-full justify-start text-muted-foreground hover:text-destructive"
        onClick={signOut}
      >
        <LogOut className="w-4 h-4 mr-2" />
        Sign Out
      </Button>
    </div>
  );
}

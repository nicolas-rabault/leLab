import { Toaster } from "@/components/ui/toaster";
import { Toaster as Sonner } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import Index from "./pages/Index";
import NotFound from "./pages/NotFound";
import Landing from "./pages/Landing";
import TeleoperationPage from "./pages/Teleoperation";
import Recording from "./pages/Recording";
import Calibration from "./pages/Calibration";
import Training from "./pages/Training";
import { UrdfProvider } from "./contexts/UrdfContext";

const queryClient = new QueryClient();

const App = () => (
  <QueryClientProvider client={queryClient}>
    <TooltipProvider>
      <Toaster />
      <Sonner />
      <UrdfProvider>
        <BrowserRouter>
          <Routes>
            <Route path="/" element={<Landing />} />
            <Route path="/control" element={<Index />} />
            <Route path="/teleoperation" element={<TeleoperationPage />} />
            <Route path="/recording" element={<Recording />} />
            <Route path="/calibration" element={<Calibration />} />
            <Route path="/training" element={<Training />} />
            {/* ADD ALL CUSTOM ROUTES ABOVE THE CATCH-ALL "*" ROUTE */}
            <Route path="*" element={<NotFound />} />
          </Routes>
        </BrowserRouter>
      </UrdfProvider>
    </TooltipProvider>
  </QueryClientProvider>
);

export default App;
